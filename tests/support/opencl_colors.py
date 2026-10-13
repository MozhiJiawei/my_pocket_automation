"""Batch the unchanged host color contract on a GPU; Lua still chooses actions.

Features come from the production Lua catalog, never labels or predictions.
Small UI regions stay on CPU to avoid GPU transfer/dispatch overhead.
"""
from pathlib import Path
import numpy as np
import pyopencl as cl
from tests.support.touchsprite_adapter import Screen



class GpuScreen(Screen):
    engine = None
    groups = None
    query_groups = None
    all_queries = {}
    all_kernel = None
    anchor_kernel = None
    candidate_kernel = None

    @classmethod
    def available(cls):
        try:
            return any(d.type & cl.device_type.GPU for p in cl.get_platforms() for d in p.get_devices())
        except cl.Error:
            return False

    @classmethod
    def configure_catalog(cls, *catalogs, enumerate_catalogs=()):
        if cls.groups is not None:
            return
        cls.groups = []
        cls.query_groups = {}
        cls.all_queries = {}
        collections=[(catalog,features) for catalog in catalogs for _,features in catalog.items()]
        for catalog, features in collections:
            queries = []
            def add(feature):
                queries.append((int(feature['base']), feature['offsets'], feature['degree'] or 90,
                                *(int(feature['region'][i]) for i in range(1, 5))))
                for i in range(1, len(feature['variants'] or []) + 1):
                    add(feature['variants'][i])
            for i in range(1, len(features)+1):
                add(features[i])
            group = tuple(dict.fromkeys(queries))
            cls.groups.append(group)
            for query in group:
                cls.query_groups.setdefault(query, len(cls.groups)-1)
                if any(catalog is c for c in enumerate_catalogs):cls.all_queries.setdefault(query[:3],(len(cls.groups)-1,query))

    @classmethod
    def get_engine(cls):
        if cls.engine is None:
            devices = [d for p in cl.get_platforms() for d in p.get_devices()
                       if d.type & cl.device_type.GPU]
            device = max(devices, key=lambda d: ('NVIDIA' in d.vendor, d.max_compute_units))
            context = cl.Context([device])
            queue = cl.CommandQueue(context)
            program = cl.Program(context, Path(__file__).with_name('color_search.cl').read_text()).build()
            cls.engine = context, queue, cl.Kernel(program, 'search'), {}
            cls.all_kernel=cl.Kernel(program,'search_all')
            cls.anchor_kernel=cl.Kernel(program,'anchors')
            cls.candidate_kernel=cl.Kernel(program,'match_anchors')
        return cls.engine

    def _find(self, *query):
        parent=self.all_queries.get(query[:3])
        if parent and all(query[i]>=parent[1][i] for i in (3,4)) and all(query[i]<=parent[1][i] for i in (5,6)):
            group_id,root=parent
            if not hasattr(self,'all_positions'):self.all_positions={}
            if root not in self.all_positions:self._run_group(group_id,True)
            positions=self.all_positions[root]
            if positions is None:return super()._find(*query)  # Overflow: exact CPU fallback.
            if not len(positions):return -1,-1
            width=self.frame.shape[1];x=positions%width;y=positions//width
            valid=positions[(x>=query[3])&(x<=query[5])&(y>=query[4])&(y<=query[6])]
            if not len(valid):return -1,-1
            first=int(valid.min());return first%width,first//width
        group_id = (self.query_groups or {}).get(query)
        if group_id is None or ((query[5]-query[3]+1)*(query[6]-query[4]+1)<100000 and len(self.groups[group_id])<16):
            return super()._find(*query)
        self._run_group(group_id)
        return self.cache[query]

    def _run_group(self, group_id, enumerate_matches=False):
        context, queue, kernel, buffers = self.get_engine()
        group = self.groups[group_id]
        batch=getattr(self,'frame_batch',None)
        image_index=getattr(self,'batch_index',0)
        if enumerate_matches and batch and group_id in batch['results']:
            self._remember_positions(batch['results'][group_id][image_index]);return
        count=len(batch['pixels']) if enumerate_matches and batch else 1
        offset=0 if enumerate_matches else image_index
        if group_id not in buffers:
            points=[];starts=[0]
            for base,offsets,*_ in group:
                points.append((0,0,base))
                points.extend((int(x),int(y),int(c,16)) for x,y,c in
                              (s.split('|') for s in offsets.split(',')))
                starts.append(len(points))
            banks={}
            for base,_,_,x1,y1,x2,y2 in group:
                old=banks.setdefault(base,[base,x1,y1,x2,y2]);old[1]=min(old[1],x1);old[2]=min(old[2],y1);old[3]=max(old[3],x2);old[4]=max(old[4],y2)
            bank_ids={base:i for i,base in enumerate(banks)}
            arrays=[np.array([q[3:] for q in group],dtype=np.int32),
                    np.array(starts,dtype=np.int32),np.array(points,dtype=np.int32),
                    np.array(list(banks.values()),dtype=np.int32),np.array([bank_ids[q[0]] for q in group],dtype=np.int32)]
            buffers[group_id]=[cl.Buffer(context,cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                                         hostbuf=a) for a in arrays]
            buffers[(group_id,'banks')]=arrays[3]
        if not hasattr(self, 'gpu_frame'):
            if batch:
                if 'buffer' not in batch:batch['buffer']=cl.Buffer(context,cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,hostbuf=batch['pixels'])
                self.gpu_frame=batch['buffer']
            else:self.gpu_frame=cl.Buffer(context,cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,hostbuf=np.ascontiguousarray(self.frame))
        height,width=self.frame.shape[:2]
        pixels=max(max(0,min(width-1,q[5])-max(0,q[3])+1)*
                   max(0,min(height-1,q[6])-max(0,q[4])+1) for q in group)
        bases=list(dict.fromkeys(q[0] for q in group));anchor_capacity=32768
        anchor_pixels=max(max(0,min(width-1,int(b[3]))-max(0,int(b[1]))+1)*
                          max(0,min(height-1,int(b[4]))-max(0,int(b[2]))+1)
                          for b in buffers[(group_id,'banks')])
        anchor_counts=np.zeros((count,len(bases)),dtype=np.int32)
        anchor_output=cl.Buffer(context,cl.mem_flags.READ_WRITE,size=count*len(bases)*anchor_capacity*4)
        anchor_count_buffer=cl.Buffer(context,cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,hostbuf=anchor_counts)
        if pixels:
            self.anchor_kernel(queue,(((anchor_pixels+255)//256)*256,len(bases),count),(256,1,1),self.gpu_frame,np.int32(width),np.int32(height),
                               buffers[group_id][3],anchor_output,anchor_count_buffer,np.int32(anchor_capacity),np.int32(len(bases)),np.int32(offset))
            cl.enqueue_copy(queue,anchor_counts,anchor_count_buffer).wait()
        candidates=int(anchor_counts.max()) if len(anchor_counts) else 0
        overflow=candidates>anchor_capacity
        if enumerate_matches:
            capacity=128;positions=np.full((count,len(group),capacity),-1,dtype=np.int32);counts=np.zeros((count,len(group)),dtype=np.int32)
            output=cl.Buffer(context,cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,hostbuf=positions)
            count_buffer=cl.Buffer(context,cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,hostbuf=counts)
            if pixels:
                if overflow:
                    self.all_kernel(queue,(pixels,len(group),count),None,self.gpu_frame,np.int32(width),np.int32(height),
                                    *buffers[group_id][:3],output,count_buffer,np.int32(capacity),np.int32(len(group)),np.int32(offset))
                elif candidates:
                    self.candidate_kernel(queue,(candidates,len(group),count),None,self.gpu_frame,np.int32(width),np.int32(height),
                        *buffers[group_id][:3],buffers[group_id][4],anchor_output,anchor_count_buffer,np.int32(anchor_capacity),
                        output,count_buffer,np.int32(capacity),np.int32(1),np.int32(len(bases)),np.int32(len(group)),np.int32(offset))
                cl.enqueue_copy(queue,positions,output);cl.enqueue_copy(queue,counts,count_buffer).wait()
            results=[{key:None if n>capacity else values[:n] for key,values,n in zip(group,row,total)}
                     for row,total in zip(positions,counts)]
            if batch:batch['results'][group_id]=results
            self._remember_positions(results[image_index if batch else 0])
            return
        result=np.full(len(group),np.iinfo(np.int32).max,dtype=np.int32)
        output=cl.Buffer(context,cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,hostbuf=result)
        pixels=max(max(0,min(width-1,q[5])-max(0,q[3])+1)*
                   max(0,min(height-1,q[6])-max(0,q[4])+1) for q in group)
        if pixels:
            if overflow:
                source=self.gpu_frame if not offset else self.gpu_frame.get_sub_region(offset*width*height*3,width*height*3)
                kernel(queue,(pixels,len(group)),None,source,np.int32(width),np.int32(height),*buffers[group_id][:3],output)
            elif candidates:
                self.candidate_kernel(queue,(candidates,len(group),count),None,self.gpu_frame,np.int32(width),np.int32(height),
                    *buffers[group_id][:3],buffers[group_id][4],anchor_output,anchor_count_buffer,np.int32(anchor_capacity),
                    output,output,np.int32(0),np.int32(0),np.int32(len(bases)),np.int32(len(group)),np.int32(offset))
            cl.enqueue_copy(queue,result,output).wait()
        for key,position in zip(group,result):
            self.cache[key]=(-1,-1) if position==np.iinfo(np.int32).max else (int(position%width),int(position//width))

    def _remember_positions(self,positions):
        self.all_positions.update(positions)
        width=self.frame.shape[1]
        for query,values in positions.items():
            if values is None:continue
            first=int(values.min()) if len(values) else -1
            self.cache[query]=(-1,-1) if first<0 else (first%width,first//width)

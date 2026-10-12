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

    @classmethod
    def available(cls):
        try:
            return any(d.type & cl.device_type.GPU for p in cl.get_platforms() for d in p.get_devices())
        except cl.Error:
            return False

    @classmethod
    def configure_catalog(cls, *catalogs):
        if cls.groups is not None:
            return
        cls.groups = []
        cls.query_groups = {}
        collections=[item for catalog in catalogs for item in catalog.items()]
        for _, features in collections:
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
        return cls.engine

    def _find(self, *query):
        group_id = (self.query_groups or {}).get(query)
        if group_id is None or (query[5]-query[3]+1)*(query[6]-query[4]+1)<100000:
            return super()._find(*query)
        context, queue, kernel, buffers = self.get_engine()
        group = self.groups[group_id]
        if group_id not in buffers:
            points=[];starts=[0]
            for base,offsets,*_ in group:
                points.append((0,0,base))
                points.extend((int(x),int(y),int(c,16)) for x,y,c in
                              (s.split('|') for s in offsets.split(',')))
                starts.append(len(points))
            arrays=[np.array([q[3:] for q in group],dtype=np.int32),
                    np.array(starts,dtype=np.int32),np.array(points,dtype=np.int32)]
            buffers[group_id]=[cl.Buffer(context,cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                                         hostbuf=a) for a in arrays]
        if not hasattr(self, 'gpu_frame'):
            self.gpu_frame=cl.Buffer(context,cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                                     hostbuf=np.ascontiguousarray(self.frame))
        height,width=self.frame.shape[:2]
        result=np.full(len(group),np.iinfo(np.int32).max,dtype=np.int32)
        output=cl.Buffer(context,cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,hostbuf=result)
        pixels=max(max(0,min(width-1,q[5])-max(0,q[3])+1)*
                   max(0,min(height-1,q[6])-max(0,q[4])+1) for q in group)
        if pixels:
            kernel(queue,(pixels,len(group)),None,self.gpu_frame,np.int32(width),np.int32(height),
                   *buffers[group_id],output)
            cl.enqueue_copy(queue,result,output).wait()
        for key,position in zip(group,result):
            self.cache[key]=(-1,-1) if position==np.iinfo(np.int32).max else (int(position%width),int(position//width))
        return self.cache[query]

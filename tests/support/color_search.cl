// Integer-only equivalent of the host max-channel-25 matcher.
inline int matched(__global const uchar *frame,int width,int height,
                   __global const int *starts,__global const int *points,
                   int feature,int x,int y) {
    for (int i=starts[feature]; i<starts[feature+1]; i++) {
        int px = x+points[i*3], py = y+points[i*3+1], color = points[i*3+2];
        if (px<0 || py<0 || px>=width || py>=height) return 0;
        int address = (py*width+px)*3;
        if (abs((int)frame[address]-(color&255))>25 ||
            abs((int)frame[address+1]-((color>>8)&255))>25 ||
            abs((int)frame[address+2]-((color>>16)&255))>25) return 0;
    }
    return 1;
}
__kernel void search(__global const uchar *frame, int width, int height,
                     __global const int *regions, __global const int *starts,
                     __global const int *points, __global int *result) {
    int feature = get_global_id(1), pixel = get_global_id(0);
    int x1 = max(0, regions[feature*4]), y1 = max(0, regions[feature*4+1]);
    int x2 = min(width-1, regions[feature*4+2]), y2 = min(height-1, regions[feature*4+3]);
    int rw = x2-x1+1, rh = y2-y1+1;
    if (rw <= 0 || rh <= 0 || pixel >= rw*rh) return;
    int x = x1 + pixel%rw, y = y1 + pixel/rw;
    if (!matched(frame,width,height,starts,points,feature,x,y)) return;
    atomic_min(&result[feature], y*width+x);
}

// Enumerate anchors once so bounded Lua subregion searches use exact results.
__kernel void search_all(__global const uchar *frame,int width,int height,
                         __global const int *regions,__global const int *starts,
                         __global const int *points,__global int *positions,
                         __global int *counts,int capacity,int feature_count,int frame_offset) {
    int feature=get_global_id(1),pixel=get_global_id(0),image=get_global_id(2);
    frame+=(image+frame_offset)*width*height*3;
    int x1=max(0,regions[feature*4]),y1=max(0,regions[feature*4+1]);
    int x2=min(width-1,regions[feature*4+2]),y2=min(height-1,regions[feature*4+3]);
    int rw=x2-x1+1,rh=y2-y1+1;
    if(rw<=0 || rh<=0 || pixel>=rw*rh) return;
    int x=x1+pixel%rw,y=y1+pixel/rw;
    if(!matched(frame,width,height,starts,points,feature,x,y)) return;
    int output=image*feature_count+feature;
    int index=atomic_inc(&counts[output]);
    if(index<capacity) positions[output*capacity+index]=y*width+x;
}

// Collect rare base-color pixels once for all directions sharing that color.
__kernel void anchors(__global const uchar *frame,int width,int height,
                      __global const int *banks,__global int *positions,
                      __global int *counts,int capacity,int bank_count,int frame_offset) {
    int bank=get_global_id(1),pixel=get_global_id(0),image=get_global_id(2);
    frame+=(image+frame_offset)*width*height*3;
    int x1=max(0,banks[bank*5+1]),y1=max(0,banks[bank*5+2]);
    int x2=min(width-1,banks[bank*5+3]),y2=min(height-1,banks[bank*5+4]);
    int rw=x2-x1+1,rh=y2-y1+1;
    int output=image*bank_count+bank;
    // Reserve a whole work group's matches with one global atomic operation.
    // All padded lanes participate in barriers; only valid pixels are sampled.
    __local int local_count;
    __local int reservation;
    if(get_local_id(0)==0) local_count=0;
    barrier(CLK_LOCAL_MEM_FENCE);
    int hit=0,x=0,y=0,index=0;
    if(rw>0 && rh>0 && pixel<rw*rh){
        x=x1+pixel%rw;y=y1+pixel/rw;
        int color=banks[bank*5],a=(y*width+x)*3;
        hit=abs((int)frame[a]-(color&255))<=25 &&
            abs((int)frame[a+1]-((color>>8)&255))<=25 &&
            abs((int)frame[a+2]-((color>>16)&255))<=25;
        if(hit) index=atomic_inc(&local_count);
    }
    barrier(CLK_LOCAL_MEM_FENCE);
    if(get_local_id(0)==0) reservation=local_count ? atomic_add(&counts[output],local_count) : 0;
    barrier(CLK_LOCAL_MEM_FENCE);
    index+=reservation;
    if(hit && index<capacity) positions[output*capacity+index]=y*width+x;
}
__kernel void match_anchors(__global const uchar *frame,int width,int height,
                     __global const int *regions,__global const int *starts,
                     __global const int *points,__global const int *bank_index,
                     __global const int *anchors,__global const int *anchor_counts,int anchor_capacity,
                     __global int *result,__global int *counts,int capacity,int enumerate,int bank_count,int feature_count,int frame_offset) {
    int feature=get_global_id(1),index=get_global_id(0),image=get_global_id(2);
    int bank=image*bank_count+bank_index[feature],output=image*feature_count+feature;
    frame+=(image+frame_offset)*width*height*3;
    if(index>=anchor_counts[bank]) return;
    int position=anchors[bank*anchor_capacity+index],x=position%width,y=position/width;
    if(x<regions[feature*4] || y<regions[feature*4+1] ||
       x>regions[feature*4+2] || y>regions[feature*4+3]) return;
    if(!matched(frame,width,height,starts,points,feature,x,y)) return;
    if(!enumerate){atomic_min(&result[output],position);return;}
    int offset=atomic_inc(&counts[output]);
    if(offset<capacity) result[output*capacity+offset]=position;
}

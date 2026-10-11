// Integer-only equivalent of the host max-channel-25 matcher.
__kernel void search(__global const uchar *frame, int width, int height,
                     __global const int *regions, __global const int *starts,
                     __global const int *points, __global int *result) {
    int feature = get_global_id(1), pixel = get_global_id(0);
    int x1 = max(0, regions[feature*4]), y1 = max(0, regions[feature*4+1]);
    int x2 = min(width-1, regions[feature*4+2]), y2 = min(height-1, regions[feature*4+3]);
    int rw = x2-x1+1, rh = y2-y1+1;
    if (rw <= 0 || rh <= 0 || pixel >= rw*rh) return;
    int x = x1 + pixel%rw, y = y1 + pixel/rw;
    for (int i=starts[feature]; i<starts[feature+1]; i++) {
        int px = x+points[i*3], py = y+points[i*3+1], color = points[i*3+2];
        if (px<0 || py<0 || px>=width || py>=height) return;
        int address = (py*width+px)*3;
        if (abs((int)frame[address]-(color&255))>25 ||
            abs((int)frame[address+1]-((color>>8)&255))>25 ||
            abs((int)frame[address+2]-((color>>16)&255))>25) return;
    }
    atomic_min(&result[feature], y*width+x);
}

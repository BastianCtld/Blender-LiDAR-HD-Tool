
int classification_to_bit_pos(uint cls) {
    switch (cls) {
        case 1: return 0;
        case 2: return 1;
        case 3: return 2;
        case 4: return 3;
        case 5: return 4;
        case 6: return 5;
        case 9: return 6;
        case 17: return 7;
        case 64: return 8;
        case 66: return 9;
        case 67: return 10;
        default: return 0;
    }
}

void main() {
    const float scale = 0.01;
    const int inverseScale = 100;
    vec3 pos = vec3(X + int(offset.x)*inverseScale, Y + int(offset.y)*inverseScale, Z + int(offset.z)*inverseScale) * scale;
    uint intensity = pack1 & 0xFFFFu;
    uint classification = (pack1 >> 16) & 0xFFu;

    vec4 offsetBounds = vec4(bounds.x+offset.x,
                        bounds.y+offset.y,
                        bounds.z+offset.x,
                        bounds.w+offset.y);

    uv = vec2((pos.x-offsetBounds.x)/(offsetBounds.z-offsetBounds.x), 1.0-(pos.y-offsetBounds.y)/(offsetBounds.w-offsetBounds.y));

    if(displayMode == 1) {
        payload = intensity;
    }
    if(displayMode == 2 || displayMode == 3) {
        payload = intensity + (classification << 16);
    }

    if((visibleClasses & (1 << int(classification_to_bit_pos(classification)))) == 0){
        gl_Position = vec4(0, 0, -10, 0);
        return;
    }

    // if(classification == 2) {
    //     gl_Position = vec4(0, 0, -10, 0);
    //     return;
    // }

    gl_Position = viewProjectionMatrix * vec4(pos, 1.0);
    if(pointSize < 0) {
        gl_PointSize = (1.0/gl_Position.w)*pointSize*-100.0;
    } else {
        gl_PointSize = pointSize;
    }
}
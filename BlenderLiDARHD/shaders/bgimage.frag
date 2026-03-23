vec4 unpackRGBA(float f) {
    uint bits = floatBitsToUint(f); // reinterpret float bits as uint

    uint r = bits & 0xFFu;
    uint g = (bits >> 8) & 0xFFu;
    uint b = (bits >> 16) & 0xFFu;
    uint a = (bits >> 24) & 0xFFu;

    return vec4(r, g, b, a) / 255.0; // normalize to 0–1
}

float toSRGB(float channel) {
    if(channel <= 0.0405) {
        return channel/12.92;
    } else {
        return pow((channel+0.055)/1.055, 2.4);
    }
}

void main() {
    // the following two lines reproduce a texture sample without interpolation
    // this is necessary for the RGBA8-to-R16F packing to work
    ivec2 texel = ivec2((uv * (vec2(textureSize(image, 0)))));
    float packedColor = texelFetch(image, texel, 0).r;

    vec4 color = unpackRGBA(packedColor);

    color.x = toSRGB(color.x);
    color.y = toSRGB(color.y);
    color.z = toSRGB(color.z);

    // if(uv.y >= 1) {
    //     FragColor = vec4(1,1,1,1);
    // } else {
    //     FragColor = color;//*brightness;
    // }
    FragColor = color;//;*brightness;
    //FragColor = vec4(uv.x,uv.y,0,1);
}
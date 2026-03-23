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

// All components are in the range [0…1], including hue.
vec3 rgb2hsv(vec3 c)
{
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));

    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

// All components are in the range [0…1], including hue.
vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
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

    if(displayMode == 0) {
        FragColor = color;
        return;
    }
    if(displayMode == 1) {
        float brightness = float(payload)/4000.0;
        FragColor = vec4(brightness,brightness,brightness,1);
        return;
    }
    if(displayMode == 2 || displayMode == 3) {
        uint intensity = payload & 0xFFFFu;
        uint classification = (payload >> 16);
        switch (classification) { // payload in this case is classification
        case 1:
            FragColor = vec4(0, 0, 0, 1);
            break;
        case 2:
            FragColor = vec4(0.377, 0.164, 0.072, 1);
            break;
        case 3:
            FragColor = vec4(0.360, 0.708, 0.222, 1);
            break;
        case 4:
            FragColor = vec4(0.181, 0.492, 0.170, 1);
            break;
        case 5:
            FragColor = vec4(0.015, 0.345, 0.0, 1);
            break;
        case 6:
            FragColor = vec4(0.608, 0.588, 0.593, 1);
            break;
        case 9:
            FragColor = vec4(0.229, 0.319, 0.577, 1);
            break;
        case 17:
            FragColor = vec4(0.692, 0.237, 0.140, 1);
            break;
        case 64:
            FragColor = vec4(0.851, 0.854, 0.847, 1);
            break;
        case 66:
            FragColor = vec4(0.692, 0.047, 0.672, 1);
            break;
        case 67:
            FragColor = vec4(0.413, 0.415, 0.412, 1);
            break;
        default:
            FragColor = vec4(0, 0, 0, 1);
            break;
        }

        if(displayMode == 3) {
            float brightness = float(intensity)/2000.0;
            FragColor = vec4(FragColor.x*brightness, FragColor.y*brightness, FragColor.z*brightness, 1);
        }
        return;
    }
    if(displayMode == 4) {
        uint intensity = payload & 0xFFFFu;
        vec3 hsv = rgb2hsv(color.xyz);
        hsv.z = float(intensity)/8000.0;
        FragColor = vec4(hsv2rgb(hsv), 1);
        return;
    }
    //FragColor = vec4(1,1,1,1);
    //FragColor = vec4(uv.x,uv.y,0,1);
}
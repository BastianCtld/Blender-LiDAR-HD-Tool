void main() {
    vec3 pos = vec3(vert.x + int(offset.x), vert.y + int(offset.y), vert.z + int(offset.z));
    uv = vertuv;
    gl_Position = viewProjectionMatrix * vec4(pos, 1.0);
    gl_Position.z = gl_Position.w - 2.4e-7;
}
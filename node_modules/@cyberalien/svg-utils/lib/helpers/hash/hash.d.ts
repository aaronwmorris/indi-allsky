/**
 * Simple hashing function, based on https://gist.github.com/jlevy/c246006675becc446360a798e2b2d781
 */
declare function hashString(str: string, seed?: number): [number, number];
export { hashString };
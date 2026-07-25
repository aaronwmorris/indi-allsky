/**
 * Calculate second dimension when only 1 dimension is set
 *
 * If you are calculating width, ratio should be width/height
 * If you are calculating height, ratio should be height/width
 */
declare function calculateSize<T extends string | number>(size: T, ratio: number, precision?: number): T;
export { calculateSize };
type Callback<T> = (item1: T, item2: T) => T | null;
/**
 * Merge arrays of items
 */
declare function mergeArrays<T>(list1: T[], list2: T[], merge: Callback<T>): T[][];
/**
 * Merge multiple arrays
 */
declare function mergeMultipleArrays<T>(lists: T[][], merge: Callback<T>): T[][];
export { mergeArrays, mergeMultipleArrays };
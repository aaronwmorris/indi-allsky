/**
 * Compare sets, returns true if identical
 */
declare function compareSets<T>(set1: Set<T> | undefined, set2: Set<T> | undefined): boolean;
/**
 * Compare two values, returns true if identical
 */
declare function compareValues<T>(value1: T, value2: T): boolean;
export { compareSets, compareValues };
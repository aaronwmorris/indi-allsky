type ComparisonKey = string | number | symbol | object;
/**
 * Compare keys, return true on match
 */
declare function compareKeys(key1: ComparisonKey, key2: ComparisonKey): boolean;
export { ComparisonKey, compareKeys };
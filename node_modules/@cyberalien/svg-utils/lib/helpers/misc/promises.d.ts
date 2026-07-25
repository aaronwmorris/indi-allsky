import { ComparisonKey } from "./keys.js";
/**
 * Make sure multiple instances of Promise or callback are not ran at the same time
 */
declare function uniquePromise<T>(key: ComparisonKey, callback: () => T | Promise<T>): Promise<T>;
export { uniquePromise };
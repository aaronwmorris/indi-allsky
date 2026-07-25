import { HashContext } from "./types.js";
/**
 * Create new hash context, used to make sure all hashes within the same context are unique
 */
declare function createUniqueHashContext(): HashContext;
export { createUniqueHashContext };
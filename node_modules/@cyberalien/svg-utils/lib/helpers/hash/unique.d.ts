import { UniqueHashOptions } from "./types.js";
/**
 * Hash an object, make sure hash is unique
 *
 * Number of unique hashes per length, with prefix for CSS:
 * 6 chars = 2b unique hashes
 * 7 chars = 78b unique hashes <-- got collision here
 * 8 chars = 2.9t unique hashes
 * 9 chars = 113t unique hashes
 *
 * Numer of unique hashes per length, with prefix for ID:
 * 6 chars = 47b unique hashes
 * 7 chars = 2.9t unique hashes
 * 8 chars = 183t unique hashes
 */
declare function getUniqueHash(data: unknown, options: UniqueHashOptions): string;
export { getUniqueHash };
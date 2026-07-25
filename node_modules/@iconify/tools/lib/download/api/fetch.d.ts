/**
 * Set custom fetch function
 */
declare function setFetch(fetchFunction: typeof fetch): void;
/**
 * Get fetch function
 */
declare function getFetch(): typeof fetch;
export { getFetch, setFetch };
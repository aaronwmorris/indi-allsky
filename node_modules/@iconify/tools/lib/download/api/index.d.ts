import { APICacheOptions, APIQueryParams, APIQueryResult } from "./types.js";
/**
 * Send API query
 */
declare function sendAPIQuery(query: APIQueryParams, cache?: APICacheOptions): Promise<APIQueryResult>;
export { sendAPIQuery };
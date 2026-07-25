/**
 * API Cache
 */
interface APICacheOptions {
  dir: string;
  ttl: number;
}
/**
 * Params
 */
interface APIQueryParams {
  uri: string;
  params?: URLSearchParams;
  headers?: Record<string, string>;
}
/**
 * Query result
 */
interface APIQuerySuccess {
  success: true;
  content: string;
}
interface APIQueryFailure {
  success: false;
  response?: Response;
  error: number;
}
type APIQueryResult = APIQuerySuccess | APIQueryFailure;
export { APICacheOptions, APIQueryParams, APIQueryResult };
import { APIQueryParams } from "./types.js";
import { RequestOptions } from "node:http";
/**
 * Axios config, customisable
 */
declare const axiosConfig: Omit<RequestOptions, 'headers' | 'responseType' | 'url' | 'method' | 'data'>;
interface AxiosCallbacks {
  onStart?: (url: string, params: APIQueryParams) => void;
  onSuccess?: (url: string, params: APIQueryParams) => void;
  onError?: (url: string, params: APIQueryParams, errorCode?: number) => void;
}
/**
 * Customisable callbacks, used for logging
 */
declare const fetchCallbacks: AxiosCallbacks;
export { axiosConfig, fetchCallbacks };
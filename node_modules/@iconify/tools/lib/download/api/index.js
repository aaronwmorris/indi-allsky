import { apiCacheKey, getAPICache, storeAPICache } from "./cache.js";
import { axiosConfig, fetchCallbacks } from "./config.js";
import { getFetch } from "./fetch.js";

/**
* Send API query
*/
async function sendAPIQuery(query, cache) {
	const cacheKey = cache ? apiCacheKey(query) : "";
	if (cache) {
		const cached = await getAPICache(cache.dir, cacheKey);
		if (cached) return {
			success: true,
			content: cached
		};
	}
	const response = await sendQuery(query);
	if (cache && response.success) try {
		await storeAPICache(cache, cacheKey, response.content);
	} catch {
		console.error("Error writing API cache");
	}
	return response;
}
/**
* Send query
*/
async function sendQuery(query) {
	const params = query.params ? query.params.toString() : "";
	const url = query.uri + (params ? "?" + params : "");
	const headers = query.headers;
	fetchCallbacks.onStart?.(url, query);
	function fail(response, status) {
		fetchCallbacks.onError?.(url, query, status);
		return {
			success: false,
			response,
			error: status ?? 404
		};
	}
	const fetch = getFetch();
	try {
		const response = await fetch(url, {
			...axiosConfig,
			headers
		});
		if (response.status !== 200) return fail(response, response.status);
		const data = await response.text();
		if (typeof data !== "string") return fail(response);
		fetchCallbacks.onSuccess?.(url, query);
		return {
			success: true,
			content: data
		};
	} catch {
		return fail();
	}
}

export { sendAPIQuery };
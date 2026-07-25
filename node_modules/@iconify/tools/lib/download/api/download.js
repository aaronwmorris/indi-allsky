import { axiosConfig, fetchCallbacks } from "./config.js";
import { getFetch } from "./fetch.js";
import { writeFile } from "node:fs/promises";

/**
* Download file
*/
async function downloadFile(query, target) {
	const params = query.params ? query.params.toString() : "";
	const url = query.uri + (params ? "?" + params : "");
	const headers = query.headers;
	fetchCallbacks.onStart?.(url, query);
	const response = await getFetch()(url, {
		...axiosConfig,
		headers
	});
	if (response.status !== 200) {
		fetchCallbacks.onError?.(url, query, response.status);
		throw new Error(`Error downloading ${url}: ${response.status}`);
	}
	const data = await response.arrayBuffer();
	fetchCallbacks.onSuccess?.(url, query);
	await writeFile(target, Buffer.from(data));
}

export { downloadFile };
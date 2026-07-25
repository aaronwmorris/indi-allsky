import { uniquePromise } from "@cyberalien/svg-utils";
import { readFile } from "node:fs/promises";

let cache;
async function getVersion() {
	const packageName = "@iconify/types/package.json";
	return cache = (await uniquePromise(packageName, async () => {
		const filename = import.meta.resolve(packageName);
		return JSON.parse(await readFile(filename.replace("file://", ""), "utf8"));
	})).version;
}
/**
* Get current version of Iconify Types package
*/
async function getTypesVersion() {
	return cache || await getVersion();
}

export { getTypesVersion };
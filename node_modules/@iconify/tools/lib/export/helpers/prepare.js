import { mkdir, rm } from "node:fs/promises";
import { normalize } from "pathe";

/**
* Normalize directory
*/
function normalizeDir(dir) {
	dir = normalize(dir);
	if (dir.slice(-1) === "/") dir = dir.slice(0, -1);
	return dir;
}
/**
* Prepare directory for export
*
* Also normalizes directory and returns normalized value
*/
async function prepareDirectoryForExport(options) {
	const dir = normalizeDir(options.target);
	if (options.cleanup) try {
		await rm(dir, {
			recursive: true,
			force: true
		});
	} catch {}
	try {
		await mkdir(dir, { recursive: true });
	} catch {}
	return dir;
}

export { normalizeDir, prepareDirectoryForExport };
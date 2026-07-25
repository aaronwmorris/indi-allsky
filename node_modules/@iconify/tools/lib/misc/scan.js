import { promises, readdirSync, statSync } from "node:fs";

/**
* Reusable functions
*/
function cleanPath(path) {
	if (path.length && path.slice(-1) !== "/") return path + "/";
	return path;
}
function isHidden(filename) {
	return filename.slice(0, 1) === ".";
}
function split(filename) {
	const parts = filename.split(".");
	return {
		ext: parts.length > 1 ? "." + parts.pop() : "",
		file: parts.join(".")
	};
}
function isIgnoredResult(result) {
	return result === void 0 || result === false || result === null;
}
async function scanDirectory(path, callback, subdirs = true) {
	const results = [];
	path = cleanPath(path);
	async function scan(subdir) {
		const files = await promises.readdir(path + subdir);
		for (let i = 0; i < files.length; i++) {
			const filename = files[i];
			if (isHidden(filename)) continue;
			let stat;
			try {
				stat = await promises.stat(path + subdir + filename);
			} catch {
				continue;
			}
			if (stat.isDirectory()) {
				if (subdirs) await scan(subdir + filename + "/");
				continue;
			}
			if (!stat.isFile()) continue;
			const { ext, file } = split(filename);
			let callbackResult;
			if (callback) {
				callbackResult = callback(ext, file, subdir, path, stat);
				if (callbackResult instanceof Promise) callbackResult = await callbackResult;
				if (isIgnoredResult(callbackResult)) continue;
			} else callbackResult = true;
			results.push(callbackResult === true ? subdir + filename : callbackResult);
		}
	}
	await scan("");
	return results;
}
function scanDirectorySync(path, callback, subdirs = true) {
	const results = [];
	path = cleanPath(path);
	function scan(subdir) {
		const files = readdirSync(path + subdir);
		for (let i = 0; i < files.length; i++) {
			const filename = files[i];
			if (isHidden(filename)) continue;
			let stat;
			try {
				stat = statSync(path + subdir + filename);
			} catch {
				continue;
			}
			if (stat.isDirectory()) {
				if (subdirs) scan(subdir + filename + "/");
				continue;
			}
			if (!stat.isFile()) continue;
			const { ext, file } = split(filename);
			let callbackResult;
			if (callback) {
				callbackResult = callback(ext, file, subdir, path, stat);
				if (isIgnoredResult(callbackResult)) continue;
			} else callbackResult = true;
			results.push(callbackResult === true ? subdir + filename : callbackResult);
		}
	}
	scan("");
	return results;
}

export { scanDirectory, scanDirectorySync };
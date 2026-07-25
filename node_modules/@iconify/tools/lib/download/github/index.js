import { prepareDirectoryForExport } from "../../export/helpers/prepare.js";
import { getGitHubRepoHash } from "./hash.js";
import { downloadFile } from "../api/download.js";
import { unzip } from "../helpers/unzip.js";
import { promises } from "node:fs";

/**
* Find matching directories
*/
async function findMatchingDirs(rootDir, hash) {
	const matches = [];
	const files = await promises.readdir(rootDir);
	for (let i = 0; i < files.length; i++) {
		const file = files[i];
		const lastChunk = file.split("-").pop();
		if (lastChunk.length < 4 || lastChunk !== hash.slice(0, lastChunk.length)) continue;
		if ((await promises.stat(rootDir + "/" + file)).isDirectory()) matches.push(file);
	}
	return matches;
}
async function downloadGitHubRepo(options) {
	const hash = await getGitHubRepoHash(options);
	const ifModifiedSince = options.ifModifiedSince;
	if (ifModifiedSince) {
		if (hash === (typeof ifModifiedSince === "string" ? ifModifiedSince : ifModifiedSince.downloadType === "github" ? ifModifiedSince.hash : null)) return "not_modified";
	}
	options.target = options.target.replace("{hash}", hash);
	const rootDir = options.target = await prepareDirectoryForExport(options);
	const archiveTarget = rootDir + "/" + hash + ".zip";
	let exists = false;
	try {
		exists = (await promises.stat(archiveTarget)).isFile();
	} catch {}
	if (!exists) await downloadFile({
		uri: `https://api.github.com/repos/${options.user}/${options.repo}/zipball/${hash}`,
		headers: {
			Accept: "application/vnd.github.v3+json",
			Authorization: "token " + options.token
		}
	}, archiveTarget);
	const files = await promises.readdir(rootDir);
	const hashSearch = "-" + hash;
	for (let i = 0; i < files.length; i++) {
		if (files[i] === hash + ".zip") continue;
		const filename = rootDir + "/" + files[i];
		const stat = await promises.lstat(filename);
		const isDir = stat.isDirectory();
		if (stat.isSymbolicLink() || isDir && filename.slice(0 - hashSearch.length) === hashSearch || isDir && options.cleanupOldDirectories !== false || !isDir && options.cleanupOldFiles) try {
			await promises.rm(filename, {
				force: true,
				recursive: true
			});
		} catch {}
	}
	await unzip(archiveTarget, rootDir, options.filter);
	const matchingDirs = await findMatchingDirs(rootDir, hash);
	if (matchingDirs.length !== 1) throw new Error(`Error unpacking ${hash}.zip`);
	return {
		downloadType: "github",
		rootDir,
		contentsDir: rootDir + "/" + matchingDirs[0],
		hash
	};
}

export { downloadGitHubRepo };
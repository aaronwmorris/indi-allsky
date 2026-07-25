import { prepareDirectoryForExport } from "../../export/helpers/prepare.js";
import { downloadFile } from "../api/download.js";
import { unzip } from "../helpers/unzip.js";
import { defaultGitLabBaseURI } from "./types.js";
import { getGitLabRepoHash } from "./hash.js";
import fs from "node:fs/promises";

/**
* Find matching directories
*/
async function findMatchingDirs(rootDir, hash) {
	const matches = [];
	const files = await fs.readdir(rootDir);
	for (let i = 0; i < files.length; i++) {
		const file = files[i];
		const lastChunk = file.split("-").pop();
		if (lastChunk.length < 4 || lastChunk !== hash.slice(0, lastChunk.length)) continue;
		if ((await fs.stat(rootDir + "/" + file)).isDirectory()) matches.push(file);
	}
	return matches;
}
async function downloadGitLabRepo(options) {
	const hash = await getGitLabRepoHash(options);
	const ifModifiedSince = options.ifModifiedSince;
	if (ifModifiedSince) {
		if (hash === (typeof ifModifiedSince === "string" ? ifModifiedSince : ifModifiedSince.downloadType === "gitlab" ? ifModifiedSince.hash : null)) return "not_modified";
	}
	options.target = options.target.replace("{hash}", hash);
	const rootDir = options.target = await prepareDirectoryForExport(options);
	const archiveTarget = rootDir + "/" + hash + ".zip";
	let exists = false;
	try {
		exists = (await fs.stat(archiveTarget)).isFile();
	} catch {}
	if (!exists) await downloadFile({
		uri: `${options.uri || defaultGitLabBaseURI}/${options.project}/repository/archive.zip?sha=${hash}`,
		headers: { Authorization: "token " + options.token }
	}, archiveTarget);
	const files = await fs.readdir(rootDir);
	const hashSearch = "-" + hash;
	for (let i = 0; i < files.length; i++) {
		if (files[i] === hash + ".zip") continue;
		const filename = rootDir + "/" + files[i];
		const stat = await fs.lstat(filename);
		const isDir = stat.isDirectory();
		if (stat.isSymbolicLink() || isDir && filename.slice(0 - hashSearch.length) === hashSearch || isDir && options.cleanupOldDirectories !== false || !isDir && options.cleanupOldFiles) try {
			await fs.rm(filename, {
				force: true,
				recursive: true
			});
		} catch {}
	}
	await unzip(archiveTarget, rootDir, options.filter);
	const matchingDirs = await findMatchingDirs(rootDir, hash);
	if (matchingDirs.length !== 1) throw new Error(`Error unpacking ${hash}.zip`);
	return {
		downloadType: "gitlab",
		rootDir,
		contentsDir: rootDir + "/" + matchingDirs[0],
		hash
	};
}

export { downloadGitLabRepo };
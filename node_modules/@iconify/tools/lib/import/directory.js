import { SVG } from "../svg/index.js";
import { cleanupSVG } from "../svg/cleanup.js";
import { blankIconSet } from "../icon-set/index.js";
import { scanDirectory, scanDirectorySync } from "../misc/scan.js";
import { cleanupIconKeyword } from "../misc/keyword.js";
import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";

function importDir(iconSet, options, getKeyword, files, readFile, done) {
	let i = 0;
	const next = () => {
		if (i >= files.length) return done(iconSet);
		const file = files[i];
		i++;
		getKeyword([
			file,
			cleanupIconKeyword(file.file),
			iconSet
		], (keyword) => {
			if (typeof keyword !== "string" || !keyword.length) return next();
			readFile(file.path + file.subdir + file.file + file.ext, (content) => {
				try {
					const svg = new SVG(content);
					cleanupSVG(svg, options);
					iconSet.fromSVG(keyword, svg);
				} catch (err) {
					const ignore = options.ignoreImportErrors ?? false;
					if (ignore === false || ignore === "warn") {
						let msg = `Failed to import "${keyword}"`;
						if (err instanceof Error) msg += `: ${err.message}`;
						if (ignore === false) throw new Error(msg);
						else console.warn(msg);
					}
				}
				next();
			});
		});
	};
	next();
}
function isValidFile(item) {
	return item.ext.toLowerCase() === ".svg";
}
/**
* Import all icons from directory
*/
function importDirectory(path, options = {}) {
	return new Promise((fulfill, reject) => {
		scanDirectory(path, (ext, file, subdir, path) => {
			const result = {
				file,
				ext,
				subdir,
				path
			};
			return isValidFile(result) ? result : false;
		}, options.includeSubDirs !== false).then((files) => {
			const iconSet = blankIconSet(options.prefix || "");
			try {
				importDir(iconSet, options, (params, done) => {
					if (options.keyword) {
						const result = options.keyword(...params);
						if (result instanceof Promise) result.then(done).catch(reject);
						else done(result);
					} else done(params[1]);
				}, files, (filename, done) => {
					readFile(filename, "utf8").then(done).catch(reject);
				}, fulfill);
			} catch (err) {
				reject(err);
			}
		}).catch(reject);
	});
}
/**
* Import all icons from directory synchronously
*/
function importDirectorySync(path, options = {}) {
	const files = scanDirectorySync(path, (ext, file, subdir, path) => {
		const result = {
			file,
			ext,
			subdir,
			path
		};
		return isValidFile(result) ? result : false;
	}, options.includeSubDirs !== false);
	const iconSet = blankIconSet(options.prefix || "");
	let isSync = true;
	importDir(iconSet, options, (params, done) => {
		if (options.keyword) done(options.keyword(...params));
		else done(params[1]);
	}, files, (filename, done) => {
		done(readFileSync(filename, "utf8"));
	}, () => {
		if (!isSync) throw new Error("importDirectorySync supposed to be synchronous");
	});
	isSync = false;
	return iconSet;
}

export { importDirectory, importDirectorySync };
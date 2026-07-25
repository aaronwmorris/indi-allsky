import { SVG } from "../../svg/index.js";
import { cleanupSVG } from "../../svg/cleanup.js";
import { blankIconSet } from "../../icon-set/index.js";
import { getFigmaIconNodes } from "./nodes.js";
import { figmaDownloadImages, figmaFilesQuery, figmaImagesQuery } from "./query.js";

async function importFromFigma(options) {
	const cacheOptions = options.cacheDir ? {
		ttl: options.cacheAPITTL || 3600 * 24,
		dir: options.cacheDir
	} : void 0;
	const cacheSVGOptions = options.cacheDir ? {
		ttl: options.cacheSVGTTL || 3600 * 24 * 30,
		dir: options.cacheDir
	} : void 0;
	const document = await figmaFilesQuery(options, cacheOptions);
	if (document === "not_modified") return document;
	options.version = document.version;
	const nodes = getFigmaIconNodes(document, options);
	await figmaImagesQuery(options, nodes, cacheOptions);
	await figmaDownloadImages(nodes, cacheSVGOptions);
	const iconSet = blankIconSet(options.prefix);
	const icons = nodes.icons;
	const missing = [];
	const iconIDs = Object.keys(icons);
	for (let i = 0; i < iconIDs.length; i++) {
		const item = icons[iconIDs[i]];
		if (typeof item.content !== "string") {
			missing.push(item);
			continue;
		}
		if (options.beforeImportingIcon) {
			const callbackResult = options.beforeImportingIcon(item, iconSet);
			if (callbackResult instanceof Promise) await callbackResult;
		}
		try {
			const svg = new SVG(item.content);
			cleanupSVG(svg);
			iconSet.fromSVG(item.keyword, svg);
		} catch {
			missing.push(item);
			continue;
		}
		if (options.afterImportingIcon) {
			const callbackResult = options.afterImportingIcon(item, iconSet);
			if (callbackResult instanceof Promise) await callbackResult;
		}
	}
	return {
		name: document.name,
		version: document.version,
		lastModified: document.lastModified,
		nodesCount: nodes.nodesCount,
		generatedIconsCount: nodes.generatedIconsCount,
		downloadedIconsCount: nodes.downloadedIconsCount,
		iconSet,
		missing
	};
}

export { importFromFigma };
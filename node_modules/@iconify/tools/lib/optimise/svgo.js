import { parseXMLContent, stringifyXMLContent } from "@cyberalien/svg-utils";
import { optimize } from "svgo";
import { changeSVGIDs } from "@cyberalien/svg-utils/lib/svg/ids/change.js";

/**
* Get list of plugins
*/
function getSVGOPlugins(options) {
	return [
		"cleanupAttrs",
		"mergeStyles",
		"inlineStyles",
		"removeComments",
		"removeUselessDefs",
		"removeEditorsNSData",
		"removeEmptyAttrs",
		"removeEmptyContainers",
		"convertStyleToAttrs",
		"convertColors",
		"convertTransform",
		"removeUnknownsAndDefaults",
		"removeNonInheritableGroupAttrs",
		"removeUnusedNS",
		"cleanupNumericValues",
		"cleanupListOfValues",
		"moveElemsAttrsToGroup",
		"moveGroupAttrsToElems",
		"collapseGroups",
		"sortDefsChildren",
		"sortAttrs",
		...options.animated ? [] : ["removeUselessStrokeAndFill"],
		...options.animated || options.keepShapes ? [] : [
			"removeHiddenElems",
			"convertShapeToPath",
			"convertEllipseToCircle",
			{
				name: "convertPathData",
				params: { noSpaceAfterFlags: true }
			},
			{
				name: "mergePaths",
				params: { noSpaceAfterFlags: true }
			},
			"reusePaths"
		],
		...!options.animated && options.cleanupIDs !== false ? ["cleanupIds"] : []
	];
}
/**
* Run SVGO on icon
*/
function runSVGO(svg, options = {}) {
	const code = svg.toString();
	const multipass = options.multipass !== false;
	let plugins;
	if (options.plugins) plugins = options.plugins;
	else {
		const animated = code.includes("<animate") || code.includes("<set");
		plugins = getSVGOPlugins({
			...options,
			animated
		});
		if (code.includes("filter=") && code.includes("transform=")) plugins = plugins.filter((item) => item !== "moveElemsAttrsToGroup");
	}
	const result = optimize(code, {
		plugins,
		multipass
	});
	if (typeof result.error === "string") throw new Error(result.error);
	let content = result.data.replace(/<defs\/>/g, "");
	if (!options.plugins) {
		const prefix = options.cleanupIDs !== void 0 ? options.cleanupIDs : "svgID";
		if (prefix !== false) {
			let counter = 0;
			const xml = parseXMLContent(content);
			if (xml) {
				changeSVGIDs(xml, () => prefix + (counter++).toString(36));
				const newContent = stringifyXMLContent(xml);
				if (newContent) content = newContent;
			}
		}
	}
	if (!options.plugins || options.plugins.find((item) => {
		if (typeof item === "string") return item === "reusePaths";
		return item.name === "reusePaths";
	})) content = content.replace(" xmlns:xlink=\"http://www.w3.org/1999/xlink\"", "").replaceAll("xlink:href=", "href=");
	svg.load(content);
}

export { getSVGOPlugins, runSVGO };
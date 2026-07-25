import { createEmptyStylesheet, stringifyStylesheet } from "../../../css/stylesheet.js";
import { getGeneratedCSSFilename } from "../filenames/css.js";
import { renderStatefulSVGCSSIconStyle } from "../../../svg-css/icon/css.js";
/**
* Generate CSS files for component
*
* Adds imports to imports object, adds assets
*/
function generateCSSFilesForComponent(content, imports, assets, options) {
	if (!content.classes) return;
	const { cssMode, componentType } = options;
	const isComponent = cssMode === "embed";
	const returnCSS = isComponent || cssMode === "prop";
	const mergeCSS = (returnCSS || options.mergeCSS) ?? false;
	const commonStylesheet = mergeCSS ? createEmptyStylesheet() : void 0;
	const statefulData = content.statefulData;
	const stylesheets = renderStatefulSVGCSSIconStyle(content, statefulData?.context ?? null, commonStylesheet);
	if (isComponent && componentType === "svelte") {
		const list = commonStylesheet ? [commonStylesheet] : Object.values(stylesheets);
		const wrapSelectors = (selectors) => {
			const keys = Object.keys(selectors);
			for (const selector of keys) {
				const value = selectors[selector];
				if (!selector.startsWith("@")) {
					delete selectors[selector];
					const newSelector = selector.split(",").map((item) => `:global(${item.trim()})`).join(", ");
					selectors[newSelector] = value;
				}
				if (value.nested) wrapSelectors(value.nested);
			}
		};
		for (const stylesheet of list) {
			wrapSelectors(stylesheet.selectors);
			const keyframes = stylesheet.keyframes;
			const animations = Object.keys(keyframes);
			for (const animationName of animations) {
				const animation = keyframes[animationName];
				delete keyframes[animationName];
				keyframes["-global-" + animationName] = animation;
			}
		}
	}
	if (!mergeCSS) for (const className in stylesheets) {
		const stylesheet = stylesheets[className];
		const content = stringifyStylesheet(stylesheet, options.legacyCSS);
		if (content) {
			const filename = getGeneratedCSSFilename(className, options);
			assets.push({
				...filename,
				content
			});
			imports.css.add(filename.import);
		}
	}
	else if (typeof mergeCSS == "object") {
		const content = stringifyStylesheet(commonStylesheet, options.legacyCSS);
		if (content) {
			assets.push({
				...mergeCSS,
				content
			});
			imports.css.add(mergeCSS.import);
		}
	}
	return returnCSS ? commonStylesheet : void 0;
}
export { generateCSSFilesForComponent };

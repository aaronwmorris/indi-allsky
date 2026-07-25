import { getGeneratedAssetFilename } from "./asset.js";
/**
* Generate CSS filename based on options
*/
function getGeneratedCSSFilename(name, options) {
	const { cssPath, doubleDirsForCSS } = options;
	return getGeneratedAssetFilename(`${doubleDirsForCSS ? `${name.slice(0, 1).toLowerCase()}/${name}` : name}.css`, cssPath);
}
export { getGeneratedCSSFilename };

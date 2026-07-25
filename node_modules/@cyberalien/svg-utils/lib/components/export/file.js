import { getGeneratedComponentFilename } from "./filename.js";
/**
* Add icon and filename to generated component
*/
function convertGeneratedComponentToFile(icon, item, options) {
	const { prefix, name } = icon;
	const filename = getGeneratedComponentFilename(icon, options.extension, options);
	return {
		icon: options.includePrefix ? `${typeof options.includePrefix === "string" ? options.includePrefix : prefix}/${name}` : name,
		filename,
		css: item.style ? getGeneratedComponentFilename(icon, options.cssExtension ?? ".css", options) : void 0,
		...item
	};
}
export { convertGeneratedComponentToFile };

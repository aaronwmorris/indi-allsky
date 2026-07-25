/**
* Get relative path to root directory from component
*
* @param options Factory options
* @returns Asset path
*/
function getFactoryRelativeRootPath(options, pathPrefix) {
	const { prefixDirsForComponents } = options;
	const prefixDir = prefixDirsForComponents ? typeof prefixDirsForComponents === "string" ? prefixDirsForComponents : "prefix" : "";
	const parentCount = (prefixDir ? prefixDir.split("/").length : 0) + (options.doubleDirsForComponents ? 1 : 0);
	return {
		import: parentCount ? "../".repeat(parentCount - 1) + ".." : ".",
		filename: pathPrefix ?? ""
	};
}
export { getFactoryRelativeRootPath };

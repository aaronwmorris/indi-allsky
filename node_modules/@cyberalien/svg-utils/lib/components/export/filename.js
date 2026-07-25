/**
* Generate component filename based on options
*
* @param icon Icon data (name and prefix)
* @param componentExtension Component file extension (e.g. '.tsx')
* @param options Factory options
* @returns Generated filename
*/
function getGeneratedComponentFilename(icon, componentExtension, options) {
	const { name, prefix } = icon;
	const { prefixDirsForComponents } = options;
	return (prefixDirsForComponents ? `${typeof prefixDirsForComponents === "string" ? prefixDirsForComponents : prefix}/` : "") + (options.doubleDirsForComponents ? `${name.slice(0, 1).toLowerCase()}/` : "") + name + componentExtension;
}
export { getGeneratedComponentFilename };

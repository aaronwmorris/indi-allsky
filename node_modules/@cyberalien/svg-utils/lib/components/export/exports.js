/**
* Add exports for main files to object
*/
function createExportsForMainFiles(data, options = {}) {
	const result = options?.data || Object.create(null);
	const ext = options.ext || "";
	const defaultProp = options.defaultProp || "default";
	for (const { icon, filename, css, types } of data) {
		result[`./${icon}${ext}`] = types ? {
			types: `./${types}`,
			[defaultProp]: `./${filename}`
		} : `./${filename}`;
		if (css) result[`./${icon}.css`] = `./${css}`;
	}
	return result;
}
export { createExportsForMainFiles };

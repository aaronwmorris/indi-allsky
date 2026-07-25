import { stringifyStylesheet } from "../../css/stylesheet.js";
/**
* Merge exported component files into single array
*/
function mergeExportedComponentFiles(items, files) {
	const added = new Set(files?.map((item) => item.filename));
	files = files ?? [];
	const add = ({ filename, content }) => {
		if (!added.has(filename)) {
			added.add(filename);
			files.push({
				filename,
				content
			});
		}
	};
	for (const item of items) {
		for (const asset of item.assets) add(asset);
		add(item);
		if (item.css && item.style) add({
			filename: item.css,
			content: stringifyStylesheet(item.style)
		});
	}
	return files;
}
export { mergeExportedComponentFiles };

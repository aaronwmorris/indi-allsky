/**
* Extract definitions from SVG
*
* Can be used with other tags, but name kept for backwards compatibility.
* Should be used only with tags that cannot be nested, such as masks, clip paths, etc.
*/
function splitSVGDefs(content, tag = "defs") {
	let defs = "";
	let index;
	while ((index = content.indexOf("<" + tag)) !== -1) {
		const start = content.indexOf(">", index);
		if (start === -1) break;
		const prevContent = content.slice(0, index).trim();
		if (content[start - 1] === "/") {
			content = prevContent + content.slice(start + 1);
			continue;
		}
		const end = content.indexOf("</" + tag);
		if (end === -1) break;
		const endEnd = content.indexOf(">", end);
		if (endEnd === -1) break;
		defs += content.slice(start + 1, end).trim();
		content = prevContent + content.slice(endEnd + 1);
	}
	return {
		defs,
		content
	};
}
/**
* Merge defs and content
*/
function mergeDefsAndContent(defs, content) {
	return defs ? `<defs>${defs}</defs>${content}` : content;
}
/**
* Wrap SVG content, without wrapping definitions
*/
function wrapSVGContent(body, start, end) {
	const split = splitSVGDefs(body);
	return mergeDefsAndContent(split.defs, start + split.content + end);
}
export { mergeDefsAndContent, splitSVGDefs, wrapSVGContent };

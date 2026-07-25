/**
* Parse SVG content
*
* Returns null on error
*/
function parseXMLContent(content, trim = true) {
	const stack = [];
	const rootNodes = [];
	let startIndex = 0;
	let parentNode = null;
	do {
		const start = content.indexOf("<", startIndex);
		const end = start === -1 ? -1 : content.indexOf(">", start);
		if (start === -1 || end === -1) {
			if (content.slice(startIndex).trim() || parentNode || !rootNodes.length) return null;
			return rootNodes;
		}
		if (content.slice(start, start + 4) === "<!--") {
			const end = content.indexOf("-->", start);
			if (end === -1) return null;
			startIndex = end + 3;
			continue;
		}
		const rawText = content.slice(startIndex, start);
		const text = trim ? rawText.trim() : rawText;
		startIndex = start;
		if (text) {
			if (!parentNode) return null;
			parentNode.children.push({
				type: "text",
				content: text
			});
		}
		let tagContent = content.slice(start + 1, end).trim();
		if (tagContent.startsWith("/")) {
			if (!parentNode) return null;
			const tagNameMatch = tagContent.slice(1).match(/^[^\s]+/);
			if (parentNode.tag !== tagNameMatch?.[0]) return null;
			stack.pop();
			parentNode = stack.length ? stack[stack.length - 1] : null;
			startIndex = end + 1;
			continue;
		}
		const tagNameMatch = tagContent.match(/^[^\s/]+/);
		if (!tagNameMatch) return null;
		const tagName = tagNameMatch[0];
		tagContent = tagContent.slice(tagName.length).trim();
		const selfClosing = tagContent.slice(-1) === "/";
		if (selfClosing) tagContent = tagContent.slice(0, -1).trim();
		const attribs = Object.create(null);
		Array.from(tagContent.matchAll(/([\w:-]+)="([^"]*)"/g) ?? []).forEach((match) => {
			attribs[match[1]] = match[2];
		});
		const element = {
			type: "tag",
			tag: tagName,
			attribs,
			children: []
		};
		if (parentNode) parentNode.children.push(element);
		else rootNodes.push(element);
		if (!selfClosing) {
			stack.push(element);
			parentNode = element;
		}
		startIndex = end + 1;
		if (tagName === "style" && !selfClosing) {
			const end = content.indexOf("</style>", startIndex);
			if (end === -1) return null;
			const css = content.slice(startIndex, end).trim();
			if (css.length) parentNode.children.push({
				type: "text",
				content: css
			});
			stack.pop();
			parentNode = stack.length ? stack[stack.length - 1] : null;
			startIndex = end + 8;
		}
	} while (true);
}
export { parseXMLContent };

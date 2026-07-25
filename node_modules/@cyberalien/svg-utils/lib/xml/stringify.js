const defaultOptions = {
	useSelfClosing: true,
	numberTemplate: ` {key}="{value}"`,
	prettyPrint: false
};
function assertNever(v) {}
/**
* Convert parsed XML content to string
*/
function stringifyXMLContent(root, options) {
	const fullOptions = {
		...defaultOptions,
		...options
	};
	const { prettyPrint } = fullOptions;
	let output = "";
	const tab = typeof prettyPrint === "string" ? prettyPrint : prettyPrint ? "	" : "";
	const tabs = (length) => tab.repeat(length);
	const nl = prettyPrint === false ? "" : "\n";
	const add = (node, depth) => {
		if (node.type !== "tag") {
			output += node.content;
			return true;
		}
		output += tabs(depth) + "<" + node.tag;
		for (const key in node.attribs) {
			const value = node.attribs[key];
			switch (typeof value) {
				case "string":
					output += ` ${key}="${value}"`;
					break;
				case "number":
					output += fullOptions.numberTemplate.replace("{value}", value.toString()).replace("{key}", key);
					break;
			}
		}
		if (!node.children.length) {
			if (fullOptions.useSelfClosing) output += (prettyPrint ? " " : "") + "/>" + nl;
			else output += "></" + node.tag + ">" + nl;
			return true;
		}
		output += ">" + nl;
		for (let i = 0; i < node.children.length; i++) {
			const childNode = node.children[i];
			switch (childNode.type) {
				case "tag":
					if (!add(childNode, depth + 1)) return false;
					break;
				case "text":
					output += childNode.content;
					break;
				default: assertNever(childNode);
			}
		}
		output += tabs(depth) + "</" + node.tag + ">" + nl;
		return true;
	};
	for (const node of root) if (!add(node, 0)) return null;
	return output;
}
export { stringifyXMLContent };

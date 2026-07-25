function iterateXMLContent(root, callback) {
	const stack = [];
	let aborted = false;
	function parseChildren(nodes) {
		const remove = [];
		for (const node of nodes) if (parse(node) === "remove") remove.push(node);
		return remove.length ? nodes.filter((item) => !remove.includes(item)) : nodes;
	}
	function parse(node) {
		if (aborted) return;
		const result = callback(node, stack);
		switch (result) {
			case "abort": aborted = true;
			case "remove":
			case "skip": return result;
		}
		if (node.type === "tag") {
			stack.push(node);
			node.children = parseChildren(node.children);
			stack.pop();
		}
	}
	return parseChildren(root);
}
export { iterateXMLContent };

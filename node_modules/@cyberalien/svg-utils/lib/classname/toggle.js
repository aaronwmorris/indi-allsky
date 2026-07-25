import { defaultClassProp } from "./const.js";
/**
* Split class name by spaces
*/
function splitClassName(className) {
	return className.trim().split(/\s+/);
}
/**
* Add/remove class name
*/
function toggleClassName(attribs, className, add, prop = defaultClassProp) {
	const oldValue = attribs[prop];
	if (typeof oldValue !== "string") {
		attribs[prop] = className;
		return;
	}
	const list = new Set(oldValue.split(/\s+/g));
	if (!add) {
		if (!list.has(className)) return;
		list.delete(className);
	} else {
		if (list.has(className)) return;
		list.add(className);
	}
	attribs[prop] = Array.from(list).sort().join(" ");
}
export { splitClassName, toggleClassName };

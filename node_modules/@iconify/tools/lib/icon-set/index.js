import { SVG } from "../svg/index.js";
import { defaultCommonProps, filterProps } from "./props.js";
import { mergeIconData, trimSVG } from "@iconify/utils";
import { defaultIconDimensions, defaultIconProps as defaultIconProps$1 } from "@iconify/utils/lib/icon/defaults";
import { iconToSVG as iconToSVG$1 } from "@iconify/utils/lib/svg/build";
import { minifyIconSet } from "@iconify/utils/lib/icon-set/minify";
import { convertIconSetInfo } from "@iconify/utils/lib/icon-set/convert-info";

function assertNever(v) {}
const themeKeys = ["prefixes", "suffixes"];
/**
* Sort theme keys: long keys first
*
* Applies changes to parameter, but also returns it
*/
function sortThemeKeys(keys) {
	return keys.sort((a, b) => a.length === b.length ? a.localeCompare(b) : b.length - a.length);
}
/**
* Export icon set
*/
var IconSet = class {
	/**
	* Properties. You can write directly to almost any property, but avoid writing to
	* 'entries' and 'categories' properties, there are functions for that.
	*/
	prefix;
	lastModified;
	entries;
	info;
	categories;
	prefixes;
	suffixes;
	/**
	* Load icon set
	*/
	constructor(data) {
		this.load(data);
	}
	/**
	* Load icon set
	*/
	load(data) {
		this.prefix = data.prefix;
		const defaultProps = filterProps(data, defaultIconDimensions, true);
		this.entries = Object.create(null);
		const entries = this.entries;
		for (const name in data.icons) {
			const item = data.icons[name];
			entries[name] = {
				type: "icon",
				body: item.body,
				props: filterProps({
					...defaultProps,
					...item
				}, defaultCommonProps, true),
				chars: /* @__PURE__ */ new Set(),
				categories: /* @__PURE__ */ new Set()
			};
		}
		if (data.aliases) for (const name in data.aliases) {
			if (entries[name]) continue;
			const item = data.aliases[name];
			const parent = item.parent;
			const props = filterProps(item, defaultCommonProps, false);
			const chars = /* @__PURE__ */ new Set();
			if (Object.keys(props).length) entries[name] = {
				type: "variation",
				parent,
				props,
				chars
			};
			else entries[name] = {
				type: "alias",
				parent,
				chars
			};
		}
		this.info = data.info && convertIconSetInfo(data.info) || void 0;
		if (data.chars) for (const char in data.chars) {
			const icon = entries[data.chars[char]];
			if (icon) icon.chars.add(char);
		}
		this.categories = /* @__PURE__ */ new Set();
		if (data.categories) for (const category in data.categories) {
			const item = {
				title: category,
				count: 0
			};
			data.categories[category].forEach((iconName) => {
				const icon = entries[iconName];
				switch (icon?.type) {
					case "icon": icon.categories.add(item);
				}
			});
			this.categories.add(item);
			this.listCategory(item);
		}
		const prefixes = this.prefixes = Object.create(null);
		const suffixes = this.suffixes = Object.create(null);
		if (data.themes) for (const key in data.themes) {
			const item = data.themes[key];
			if (typeof item.prefix === "string") {
				const prefix = item.prefix;
				if (prefix.slice(-1) === "-") prefixes[prefix.slice(0, -1)] = item.title;
			}
			if (typeof item.suffix === "string") {
				const suffix = item.suffix;
				if (suffix.slice(0, 1) === "-") suffixes[suffix.slice(1)] = item.title;
			}
		}
		themeKeys.forEach((prop) => {
			const items = data[prop];
			if (items) {
				this[prop] = Object.create(null);
				for (const key in items) this[prop][key] = items[key];
			}
		});
		this.lastModified = data.lastModified || 0;
	}
	/**
	* Update last modification time
	*/
	updateLastModified(value) {
		this.lastModified = value || Math.floor(Date.now() / 1e3);
	}
	/**
	* List icons
	*/
	list(types = ["icon", "variation"]) {
		return Object.keys(this.entries).filter((name) => types.includes(this.entries[name].type));
	}
	/**
	* forEach function to loop through all entries.
	* Supports asynchronous callbacks.
	*
	* Callback should return false to stop loop.
	*/
	async forEach(callback, types = [
		"icon",
		"variation",
		"alias"
	]) {
		const names = this.list(types);
		for (let i = 0; i < names.length; i++) {
			const name = names[i];
			const item = this.entries[name];
			if (item) {
				let result = callback(name, item.type);
				if (result instanceof Promise) result = await result;
				if (result === false) return;
			}
		}
	}
	/**
	* Synchronous version of forEach function to loop through all entries.
	*
	* Callback should return false to stop loop.
	*/
	forEachSync(callback, types = [
		"icon",
		"variation",
		"alias"
	]) {
		const names = this.list(types);
		for (let i = 0; i < names.length; i++) {
			const name = names[i];
			const item = this.entries[name];
			if (item) {
				if (callback(name, item.type) === false) return;
			}
		}
	}
	/**
	* Get parent icons tree
	*
	* Returns parent icons list for each icon, null if failed to resolve.
	* In parent icons list, first element is a direct parent, last is icon. Does not include item.
	*
	* Examples:
	*   'alias3': ['alias2', 'alias1', 'icon']
	* 	 'icon': []
	* 	 'bad-icon': null
	*/
	getTree(names) {
		const entries = this.entries;
		const resolved = Object.create(null);
		function resolve(name) {
			const item = entries[name];
			if (!item) return resolved[name] = null;
			if (item.type === "icon") return resolved[name] = [];
			if (resolved[name] === void 0) {
				resolved[name] = null;
				const parent = item.parent;
				const value = parent && resolve(parent);
				if (value) resolved[name] = [parent].concat(value);
			}
			return resolved[name];
		}
		(names || Object.keys(entries)).forEach(resolve);
		return resolved;
	}
	resolve(name, full = false) {
		const entries = this.entries;
		const item = entries[name];
		const tree = item && (item.type === "icon" ? [] : this.getTree([name])[name]);
		if (!tree) return null;
		let result = {};
		function parse(name) {
			const item = entries[name];
			if (item.type === "alias") return;
			result = mergeIconData(item.props, result);
			if (item.type === "icon") result.body = item.body;
		}
		parse(name);
		tree.forEach(parse);
		return result && full ? {
			...defaultIconProps$1,
			...result
		} : result;
	}
	/**
	* Generate HTML
	*/
	toString(name, customisations = {
		width: "auto",
		height: "auto"
	}) {
		const item = this.resolve(name);
		if (!item) return null;
		const result = iconToSVG$1(item, customisations);
		return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"${Object.keys(result.attributes).map((key) => ` ${key}="${result.attributes[key]}"`).join("")}>${result.body}</svg>`;
	}
	/**
	* Get SVG instance for icon
	*/
	toSVG(name) {
		const html = this.toString(name);
		return html ? new SVG(html) : null;
	}
	/**
	* Export icon set
	*/
	export(validate = true) {
		const icons = Object.create(null);
		const aliases = Object.create(null);
		const tree = validate ? this.getTree() : Object.create(null);
		const names = Object.keys(this.entries);
		names.sort((a, b) => a.localeCompare(b));
		names.forEach((name) => {
			const item = this.entries[name];
			switch (item.type) {
				case "icon":
					icons[name] = {
						body: trimSVG(item.body),
						...item.props
					};
					break;
				case "alias":
				case "variation": {
					if (validate && !tree[name]) break;
					const props = item.type === "variation" ? item.props : {};
					aliases[name] = {
						parent: item.parent,
						...props
					};
					break;
				}
				default: assertNever(item);
			}
		});
		let info;
		if (this.info) {
			this.info.total = this.count();
			info = JSON.parse(JSON.stringify(this.info));
		}
		const result = { prefix: this.prefix };
		if (info) result.info = info;
		if (this.lastModified) result.lastModified = this.lastModified;
		result.icons = icons;
		if (Object.keys(aliases).length) result.aliases = aliases;
		const chars = this.chars(Object.keys(icons).concat(Object.keys(aliases)));
		if (Object.keys(chars).length) result.chars = chars;
		const categories = Object.create(null);
		Array.from(this.categories).sort((a, b) => a.title.localeCompare(b.title)).forEach((item) => {
			const names = this.listCategory(item);
			if (names) {
				names.sort((a, b) => a.localeCompare(b));
				categories[item.title] = names;
			}
		});
		if (Object.keys(categories).length) result.categories = categories;
		themeKeys.forEach((prop) => {
			const items = this[prop];
			const keys = Object.keys(items);
			if (keys.length) {
				const sortedTheme = Object.create(null);
				const tested = this.checkTheme(prop === "prefixes");
				keys.forEach((key) => {
					if (tested.valid[key].length) sortedTheme[key] = items[key];
				});
				if (Object.keys(sortedTheme).length) result[prop] = sortedTheme;
			}
		});
		minifyIconSet(result);
		return result;
	}
	/**
	* Get characters map
	*/
	chars(names) {
		const chars = Object.create(null);
		if (!names) names = Object.keys(this.entries);
		for (let i = 0; i < names.length; i++) {
			const name = names[i];
			this.entries[name].chars.forEach((char) => {
				chars[char] = name;
			});
		}
		return chars;
	}
	/**
	* Filter icons
	*/
	_filter(callback) {
		const names = [];
		for (const key in this.entries) {
			const item = this.entries[key];
			switch (item.type) {
				case "icon":
					if (callback(key, item)) names.push(key);
					break;
				case "variation":
				case "alias": {
					const icon = this.resolve(key);
					if (icon && callback(key, item, icon)) names.push(key);
					break;
				}
			}
		}
		return names;
	}
	/**
	* Count icons
	*/
	count() {
		return this._filter((_key, item, icon) => {
			if (item.type === "alias" || item.props.hidden || icon?.hidden) return false;
			return true;
		}).length;
	}
	/**
	* Find category by title
	*/
	findCategory(title, add) {
		const categoryItem = Array.from(this.categories).find((item) => item.title === title);
		if (categoryItem) return categoryItem;
		if (add) {
			const newItem = {
				title,
				count: 0
			};
			this.categories.add(newItem);
			return newItem;
		}
		return null;
	}
	/**
	* Count icons in category, remove category if empty
	*
	* Hidden icons and aliases do not count
	*/
	listCategory(category) {
		const categoryItem = typeof category === "string" ? this.findCategory(category, false) : category;
		if (!categoryItem) return null;
		const icons = this._filter((_key, item) => {
			if (item.type !== "icon" || item.props.hidden) return false;
			return item.categories.has(categoryItem);
		});
		const count = icons.length;
		categoryItem.count = count;
		if (!count) {
			this.categories.delete(categoryItem);
			return null;
		}
		return icons;
	}
	/**
	* Check if icon exists
	*/
	exists(name) {
		return !!this.entries[name];
	}
	/**
	* Remove icons. Returns number of removed icons
	*
	* If removeDependencies is a string, it represents new parent for all aliases of removed icon. New parent cannot be alias or variation.
	*/
	remove(name, removeDependencies = true) {
		const entries = this.entries;
		if (typeof removeDependencies === "string") {
			const item = entries[removeDependencies];
			if (name === removeDependencies || item?.type !== "icon") return 0;
		}
		if (!entries[name]) return 0;
		this.updateLastModified();
		if (typeof removeDependencies === "string") {
			for (const key in entries) {
				const item = entries[key];
				if (item.type !== "icon" && item.parent === name) item.parent = removeDependencies;
			}
			return 0;
		}
		delete entries[name];
		let count = 1;
		function remove(parent) {
			Object.keys(entries).filter((name) => {
				const item = entries[name];
				return item.type !== "icon" && item.parent === parent;
			}).forEach((name) => {
				if (entries[name]) {
					delete entries[name];
					count++;
					remove(name);
				}
			});
		}
		if (removeDependencies === true) remove(name);
		return count;
	}
	/**
	* Rename icon
	*/
	rename(oldName, newName) {
		if (oldName === newName) return false;
		const entries = this.entries;
		if (entries[newName]) {
			if (!this.remove(newName)) return false;
		}
		if (!entries[oldName]) return false;
		entries[newName] = entries[oldName];
		delete entries[oldName];
		for (const key in entries) {
			const item = entries[key];
			switch (item.type) {
				case "icon": break;
				case "alias":
				case "variation":
					if (item.parent === oldName) item.parent = newName;
					break;
				default: assertNever(item);
			}
		}
		this.updateLastModified();
		return true;
	}
	/**
	* Add/update item
	*/
	setItem(name, item) {
		switch (item.type) {
			case "alias":
			case "variation": if (!this.entries[item.parent]) return false;
		}
		this.entries[name] = item;
		this.updateLastModified();
		return true;
	}
	/**
	* Add/update icon
	*/
	setIcon(name, icon) {
		return this.setItem(name, {
			type: "icon",
			body: icon.body,
			props: filterProps(icon, defaultCommonProps, true),
			chars: /* @__PURE__ */ new Set(),
			categories: /* @__PURE__ */ new Set()
		});
	}
	/**
	* Add/update alias without props
	*/
	setAlias(name, parent) {
		return this.setItem(name, {
			type: "alias",
			parent,
			chars: /* @__PURE__ */ new Set()
		});
	}
	/**
	* Add/update alias with props
	*/
	setVariation(name, parent, props) {
		return this.setItem(name, {
			type: "variation",
			parent,
			props,
			chars: /* @__PURE__ */ new Set()
		});
	}
	/**
	* Icon from SVG. Updates old icon if it exists
	*/
	fromSVG(name, svg) {
		const props = { ...svg.viewBox };
		const body = svg.getBody();
		const item = this.entries[name];
		switch (item?.type) {
			case "icon":
			case "variation": return this.setItem(name, {
				type: "icon",
				body,
				props,
				chars: item.chars,
				categories: item.type === "icon" ? item.categories : /* @__PURE__ */ new Set()
			});
		}
		return this.setIcon(name, {
			body,
			...props
		});
	}
	/**
	* Add or remove character for icon
	*/
	toggleCharacter(iconName, char, add) {
		const item = this.entries[iconName];
		if (!item) return false;
		if (item.chars.has(char) !== add) {
			item.chars[add ? "add" : "delete"](char);
			return true;
		}
		return false;
	}
	/**
	* Add or remove category for icon
	*/
	toggleCategory(iconName, category, add) {
		const item = this.entries[iconName];
		const categoryItem = this.findCategory(category, add);
		if (!item || !categoryItem) return false;
		switch (item.type) {
			case "icon": if (item.categories.has(categoryItem) !== add) {
				categoryItem.count += add ? 1 : -1;
				item.categories[add ? "add" : "delete"](categoryItem);
				return true;
			}
		}
		return false;
	}
	/**
	* Find icons that belong to theme
	*/
	checkTheme(prefix) {
		const themes = prefix ? this.prefixes : this.suffixes;
		const keys = sortThemeKeys(Object.keys(themes));
		const results = {
			valid: Object.create(null),
			invalid: []
		};
		keys.forEach((key) => {
			results.valid[key] = [];
		});
		results.invalid = this._filter((name, item, icon) => {
			if (item.type === "alias" || item.props.hidden || icon?.hidden) return false;
			for (let i = 0; i < keys.length; i++) {
				const search = keys[i];
				if (search === "") {
					results.valid[search].push(name);
					return false;
				}
				const match = prefix ? search + "-" : "-" + search;
				const length = match.length;
				if ((prefix ? name.slice(0, length) : name.slice(0 - length)) === match) {
					results.valid[search].push(name);
					return false;
				}
			}
			return true;
		});
		return results;
	}
};
/**
* Create blank icon set
*/
function blankIconSet(prefix) {
	return new IconSet({
		prefix,
		icons: {}
	});
}

export { IconSet, blankIconSet, sortThemeKeys };
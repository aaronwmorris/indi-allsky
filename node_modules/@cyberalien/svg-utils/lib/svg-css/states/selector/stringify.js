import { stringifySelectorParts } from "./part/stringify.js";
function joinSequence(parts) {
	let selectors = [];
	for (const part of parts) {
		const chunks = part.split(",").map((s) => s.trim());
		if (!selectors.length) {
			selectors.push(...chunks);
			continue;
		}
		const newSelectors = [];
		for (const chunk of chunks) for (const selector of selectors) newSelectors.push(`${selector} ${chunk}`);
		selectors = newSelectors;
	}
	const uniqueSelectors = new Set(selectors);
	return Array.from(uniqueSelectors).sort((a, b) => a.localeCompare(b)).join(", ");
}
function mergeRules(rules) {
	const results = /* @__PURE__ */ new Set();
	for (const rule of rules) {
		const chunks = rule.split(",").map((s) => s.trim());
		for (const chunk of chunks) results.add(chunk);
	}
	return Array.from(results).sort((a, b) => a.localeCompare(b)).join(", ");
}
function mergeSequences(list1, list2) {
	const max1 = list1.length - 1;
	const max2 = list2.length - 1;
	let match1 = -1;
	let match2 = -1;
	for (let i = 0; i <= max1; i++) {
		const part1 = list1[i];
		for (let j = 0; j <= max2; j++) if (part1 === list2[j]) {
			if ((i === 0 || j === 0) && i !== j) continue;
			if ((i === max1 || j === max2) && (i !== max1 || j !== max2)) continue;
			match1 = i;
			match2 = j;
			break;
		}
		if (match1 !== -1) break;
	}
	if (match1 === -1) return [mergeRules([joinSequence(list1), joinSequence(list2)])];
	const merged = [];
	if (match1 > 0) merged.push(mergeRules([joinSequence(list1.slice(0, match1)), joinSequence(list2.slice(0, match2))]));
	merged.push(mergeRules([list1[match1], list2[match2]]));
	if (match1 < max1) merged.push(...mergeSequences(list1.slice(match1 + 1), list2.slice(match2 + 1)));
	return merged;
}
function optimiseMerge(data) {
	const result = [];
	const atRules = /* @__PURE__ */ new Map();
	const add = (sequence) => {
		const atData = [];
		let skipped = false;
		for (let i = 0; i < sequence.length; i++) {
			const part = sequence[i];
			if (part.includes("@")) {
				if (skipped) return false;
				atData.push(`${i}:${part}`);
			} else skipped = true;
		}
		const atKey = atData.join("|");
		if (!skipped) {
			result.push(sequence);
			return true;
		}
		if (atRules.has(atKey)) {
			const index = atRules.get(atKey);
			const existing = result[index];
			const merged = [];
			const minLength = Math.min(existing.length, sequence.length);
			for (let i = 0; i < minLength; i++) {
				const part1 = existing[i];
				const part2 = sequence[i];
				if (part1 === part2) {
					merged.push(part1);
					continue;
				}
				if (part1.includes("@") || part2.includes("@")) return false;
				merged.push(...mergeSequences(existing.slice(i), sequence.slice(i)));
				break;
			}
			result[index] = merged;
			return true;
		}
		atRules.set(atKey, result.length);
		result.push(sequence);
		return true;
	};
	for (const sequence of data) if (!add(sequence)) return data;
	return result;
}
function optimise(data) {
	let changed = false;
	const result = [];
	const add = (sequence) => {
		if (!result.length) {
			result.push([...sequence]);
			return;
		}
		const length = sequence.length;
		for (let i = 0; i < result.length; i++) {
			const existing = result[i];
			if (existing.length === length) {
				let matches = 0;
				let differentIndex = -1;
				for (let j = 0; j < length; j++) if (existing[j] === sequence[j]) matches++;
				else differentIndex = j;
				if (matches === length) return;
				if (matches === length - 1) {
					const part1 = sequence[differentIndex];
					const part2 = existing[differentIndex];
					if (!part1.includes("@") && !part2.includes("@")) {
						existing[differentIndex] = mergeRules([part1, part2]);
						changed = true;
						return;
					}
				}
			}
		}
		result.push([...sequence]);
	};
	for (const sequence of data) add(sequence);
	if (!changed && result.length > 1) return optimiseMerge(result);
	return changed ? optimise(result) : result;
}
/**
* Convert selector data to strings
*
* Returns sets of selector sequences
*/
function stringifySelectorsForState(data) {
	const sequences = [];
	for (const group of data) {
		const sequence = stringifySelectorParts(group);
		if (!sequence) return null;
		sequences.push(sequence);
	}
	sequences.sort((a, b) => a.length - b.length);
	return optimise(sequences);
}
export { stringifySelectorsForState };

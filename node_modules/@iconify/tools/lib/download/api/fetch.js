let customFetch = fetch;
/**
* Set custom fetch function
*/
function setFetch(fetchFunction) {
	customFetch = fetchFunction;
}
/**
* Get fetch function
*/
function getFetch() {
	return customFetch;
}

export { getFetch, setFetch };
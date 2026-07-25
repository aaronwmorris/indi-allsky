/**
* Get error message from Figma API response
*/
function getFigmaErrorMessage(status, response) {
	if (response) switch (status) {
		case 429: {
			const retryAfter = response.headers.get("Retry-After");
			return `Error retrieving document from API: rate limit exceeded.${retryAfter ? ` Try again after ${retryAfter} seconds.` : ""}`;
		}
	}
	return `Error retrieving document from API: ${status}`;
}

export { getFigmaErrorMessage };
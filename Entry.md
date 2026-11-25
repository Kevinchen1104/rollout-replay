# Rollout Replay

Two checkout rules can give access to the same number of customers while changing who gets to use the feature. Rollout Replay compares the rules for the same set of accounts using the official Flagsmith Python SDK. A release owner can set a limit on how many assignments may change before a proposed rollout needs review.

In the demo, the current rule grants access to pilot customers. The candidate grants access to customers in the west. Both enable 100 of the 200 synthetic accounts. Fifty people lose access and fifty gain it. With a 10% limit, the command exits with code 3. Comparing the original rule with itself returns 0 changes and exit code 0.

The final run fetches the current document through the official Flagsmith CLI v2.0.0 from a local test server. The tool reports aggregate results and leaves the release decision to a person. AI assisted with design, implementation, tests and the demo.

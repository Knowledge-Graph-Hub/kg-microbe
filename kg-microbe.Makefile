# Define variables
RUNNER_VERSION := 2.317.0
RUNNER_URL := https://github.com/actions/runner/releases/download/v$(RUNNER_VERSION)/actions-runner-linux-x64-$(RUNNER_VERSION).tar.gz
RUNNER_DIR := actions-runner
REPO_OWNER := Knowledge-Graph-Hub
REPO_NAME := kg-microbe
REPO_URL := https://github.com/$(REPO_OWNER)/$(REPO_NAME)
TOKEN := $(GH_TOKEN)
TRANSFORMED_TARBALL := data_transformed.tar.gz
MERGED_TARBALL := data_merged.tar.gz
PART_SIZE := 2000M  # Size of each part (less than 2GB)

.PHONY: release pre-release tag generate-tarballs split-transformed-tarball

release: generate-tarballs split-transformed-tarball
	@echo "Creating a release on GitHub..."
	@read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG_NAME; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	if git rev-parse "$$TAG_NAME" >/dev/null 2>&1; then \
		echo "Error: Tag '$$TAG_NAME' already exists. Please choose a different tag."; \
		exit 1; \
	fi; \
	git tag -a $$TAG_NAME -m "$$RELEASE_TITLE"; \
	git push origin $$TAG_NAME; \
	gh release create $$TAG_NAME --title "$$RELEASE_TITLE" --notes "$$RELEASE_NOTES" --repo $(REPO_OWNER)/$(REPO_NAME); \
	gh release upload $$TAG_NAME $(TRANSFORMED_TARBALL)-part*.tar.gz --repo $(REPO_OWNER)/$(REPO_NAME); \
	gh release upload $$TAG_NAME $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Release $$TAG_NAME created successfully."

pre-release: generate-tarballs split-transformed-tarball
	@echo "Creating a pre-release on GitHub..."
	@read -p "Enter pre-release tag (e.g., $(shell date +%Y-%m-%d)-rc1): " TAG; \
	read -p "Enter pre-release title: " PRE_RELEASE_TITLE; \
	read -p "Enter pre-release notes: " PRE_RELEASE_NOTES; \
	if git rev-parse "$$TAG" >/dev/null 2>&1; then \
		echo "Error: Tag '$$TAG' already exists. Please choose a different tag."; \
		exit 1; \
	fi; \
	git tag -a $$TAG -m "$$PRE_RELEASE_TITLE"; \
	git push origin $$TAG; \
	gh release create $$TAG --title "$$PRE_RELEASE_TITLE" --notes "$$PRE_RELEASE_NOTES" --prerelease --repo $(REPO_OWNER)/$(REPO_NAME); \
	gh release upload $$TAG $(TRANSFORMED_TARBALL)-part*.tar.gz --repo $(REPO_OWNER)/$(REPO_NAME); \
	gh release upload $$TAG $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Pre-release $$TAG created successfully."


tag: generate-tarballs split-transformed-tarball
	@echo "Creating a release on GitHub..."
	@read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	git tag -a $$TAG -m "$$RELEASE_TITLE"; \
	git push origin $$TAG; \
	gh release upload $$TAG $(TRANSFORMED_TARBALL)-part*.tar.gz --repo $(REPO_OWNER)/$(REPO_NAME); \
	gh release upload $$TAG $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Release $$TAG created successfully."

generate-tarballs:
	@echo "Generating tarballs of the specified directories..."
	@tar -czvf $(TRANSFORMED_TARBALL) data/transformed
	@cp data/merged/merged-kg.tar.gz $(MERGED_TARBALL)
	@echo "Tarballs generated successfully as $(TRANSFORMED_TARBALL) and $(MERGED_TARBALL)."

split-transformed-tarball:
	@echo "Splitting the transformed tarball into parts..."
	@split -b $(PART_SIZE) -d -a 3 $(TRANSFORMED_TARBALL) $(TRANSFORMED_TARBALL)-part
	@for f in $(TRANSFORMED_TARBALL)-part*; do mv "$$f" "$$f.tar.gz"; done
	@echo "Transformed tarball split into parts successfully."

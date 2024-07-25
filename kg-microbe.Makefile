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

.PHONY: release pre-release tag generate-tarballs split-tarballs

release: generate-tarballs split-tarballs
	@echo "Setting up GitHub Actions self-hosted runner..."
	@mkdir -p $(RUNNER_DIR)
	@cd $(RUNNER_DIR) && curl -o actions-runner.tar.gz -L $(RUNNER_URL)
	@cd $(RUNNER_DIR) && tar xzf ./actions-runner.tar.gz
	@cd $(RUNNER_DIR) && ./config.sh --url $(REPO_URL) --token $(TOKEN)
	@cd $(RUNNER_DIR) && ./run.sh &
	@echo "GitHub Actions self-hosted runner setup complete."
	@read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG_NAME; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	git tag -a $$TAG_NAME -m "$$RELEASE_TITLE"; \
	git push origin $$TAG_NAME; \
	for part in $(TRANSFORMED_TARBALL)-*.tar.gz; do \
		gh release upload $$TAG_NAME $$part --repo $(REPO_OWNER)/$(REPO_NAME); \
	done; \
	gh release upload $$TAG_NAME $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Release $$TAG_NAME created successfully."

pre-release: generate-tarballs split-tarballs
	@echo "Creating a pre-release on GitHub..."
	@read -p "Enter pre-release tag (e.g., $(shell date +%Y-%m-%d)-rc1): " TAG; \
	read -p "Enter pre-release title: " PRE_RELEASE_TITLE; \
	read -p "Enter pre-release notes: " PRE_RELEASE_NOTES; \
	git tag -a $$TAG -m "$$PRE_RELEASE_TITLE"; \
	git push origin $$TAG; \
	gh release create $$TAG --title "$$PRE_RELEASE_TITLE" --notes "$$PRE_RELEASE_NOTES" --prerelease --repo $(REPO_OWNER)/$(REPO_NAME); \
	for part in $(TRANSFORMED_TARBALL)-*.tar.gz; do \
		gh release upload $$TAG $$part --repo $(REPO_OWNER)/$(REPO_NAME); \
	done; \
	gh release upload $$TAG $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Pre-release $$TAG created successfully."

tag: generate-tarballs split-tarballs
	@echo "Creating a release on GitHub..."
	@read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	git tag -a $$TAG -m "$$RELEASE_TITLE"; \
	git push origin $$TAG; \
	for part in $(TRANSFORMED_TARBALL)-*.tar.gz; do \
		gh release upload $$TAG $$part --repo $(REPO_OWNER)/$(REPO_NAME); \
	done; \
	gh release upload $$TAG $(MERGED_TARBALL) --repo $(REPO_OWNER)/$(REPO_NAME); \
	echo "Release $$TAG created successfully."

generate-tarballs:
	@echo "Generating tarballs of the specified directories..."
	@tar -czvf $(TRANSFORMED_TARBALL) data/transformed
	@tar -czvf $(MERGED_TARBALL) -C data/merged merged-kg.tar.gz
	@echo "Tarballs generated successfully as $(TRANSFORMED_TARBALL) and $(MERGED_TARBALL)."

split-tarballs:
	@echo "Splitting transformed tarball into smaller parts..."
	@split -b $(PART_SIZE) -d -a 3 $(TRANSFORMED_TARBALL) $(TRANSFORMED_TARBALL).
	@for i in $(TRANSFORMED_TARBALL).???; do \
		n=$(shell echo $$i | sed 's/.*\.\([0-9][0-9][0-9]\)/\1/'); \
		mv $$i $(TRANSFORMED_TARBALL:.tar.gz=-$$n.tar.gz); \
	done
	@echo "Transformed tarball split into parts successfully."

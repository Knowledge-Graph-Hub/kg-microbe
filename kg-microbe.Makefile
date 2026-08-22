# Define variables
RUNNER_VERSION := 2.317.0
RUNNER_URL := https://github.com/actions/runner/releases/download/v$(RUNNER_VERSION)/actions-runner-linux-x64-$(RUNNER_VERSION).tar.gz
RUNNER_DIR := actions-runner
REPO_OWNER := Knowledge-Graph-Hub
REPO_NAME := kg-microbe
REPO_URL := https://github.com/$(REPO_OWNER)/$(REPO_NAME)
MERGED_TARBALL := data_merged.tar.gz
PART_SIZE := 2000M  # Size of each part (less than 2GB)
RELEASE_ARTIFACT_MANIFEST := .release-artifacts.txt
SELF_MAKEFILE := $(lastword $(MAKEFILE_LIST))
# Detect OS and set STAT_CMD accordingly
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Linux)
	STAT_CMD = stat -c %s
else ifeq ($(UNAME_S),Darwin)
	STAT_CMD = stat -f %z
endif

.PHONY: release pre-release tag generate-tarballs check-and-split cleanup-release-artifacts

release: generate-tarballs
	@$(call create_release,release)

pre-release: generate-tarballs
	$(call create_release,pre-release)

tag: generate-tarballs
	@$(call create_tag)

generate-tarballs:
	@echo "Generating tarballs of the specified directories..."
	@: > "$(RELEASE_ARTIFACT_MANIFEST)"
	@for dir in data/transformed/*; do \
		if [ -d "$$dir" ] && [ "$$(basename $$dir)" != "uniprot_functional_microbes" ]; then \
			if [ $$(find $$dir -type f | wc -l) -gt 0 ]; then \
				tarball_name=$$(basename $$dir).tar.gz; \
				tar -czvf $$tarball_name -C $$dir .; \
				echo "Tarball generated successfully as $$tarball_name."; \
				$(MAKE) -f "$(SELF_MAKEFILE)" check-and-split TARFILE=$$tarball_name DIR=$$dir; \
			else \
				echo "Directory $$dir is empty. Skipping tarball generation."; \
			fi \
		fi \
	done

	@if [ -d "data/merged/kg-microbe-core" ]; then \
		echo "Tarballing data/merged/kg-microbe-core..."; \
		tar -czvf kg-microbe-core.tar.gz -C data/merged/kg-microbe-core .; \
		echo "Tarball generated successfully as kg-microbe-core.tar.gz."; \
		$(MAKE) -f "$(SELF_MAKEFILE)" check-and-split TARFILE=kg-microbe-core.tar.gz DIR=data/merged/kg-microbe-core; \
	else \
		echo "Directory data/merged/kg-microbe-core does not exist. Skipping."; \
	fi

	@if [ -d "data/merged/kg-microbe-biomedical" ]; then \
		echo "Tarballing data/merged/kg-microbe-biomedical..."; \
		tar -czvf kg-microbe-biomedical.tar.gz -C data/merged/kg-microbe-biomedical .; \
		echo "Tarball generated successfully as kg-microbe-biomedical.tar.gz."; \
		$(MAKE) -f "$(SELF_MAKEFILE)" check-and-split TARFILE=kg-microbe-biomedical.tar.gz DIR=data/merged/kg-microbe-biomedical; \
	else \
		echo "Directory data/merged/kg-microbe-biomedical does not exist. Skipping."; \
	fi

	@echo "Tarballs generated successfully."

check-and-split:
	@echo "Checking if $(TARFILE) needs to be split..."
	@if [ $$($(STAT_CMD) "$(TARFILE)") -gt 2147483648 ]; then \
		echo "$(TARFILE) is larger than 2GB. Tarballing individual files..."; \
		dirname=$$(basename $(DIR)); \
		for file in $(DIR)/*; do \
			if [ -f "$$file" ]; then \
				filename=$$(basename $$file); \
                tarball_name=$${dirname}_$${filename}.tar.gz; \
				tar -czvf $$tarball_name -C $$(dirname $$file) $$(basename $$file); \
				printf '%s\n' "$$tarball_name" >> "$(RELEASE_ARTIFACT_MANIFEST)"; \
				echo "Tarball generated successfully as $$tarball_name."; \
			else \
				echo "$$file is not a regular file. Skipping."; \
			fi \
		done; \
		rm -f $(TARFILE); \
		echo "$(TARFILE) deleted after splitting."; \
	else \
		printf '%s\n' "$(TARFILE)" >> "$(RELEASE_ARTIFACT_MANIFEST)"; \
		echo "$(TARFILE) is less than 2GB. No need to split."; \
	fi

cleanup-release-artifacts:
	@if [ -f "$(RELEASE_ARTIFACT_MANIFEST)" ]; then \
		while IFS= read -r artifact; do \
			if [ -n "$$artifact" ]; then rm -f -- "$$artifact"; fi; \
		done < "$(RELEASE_ARTIFACT_MANIFEST)"; \
		rm -f -- "$(RELEASE_ARTIFACT_MANIFEST)"; \
	fi

define create_release
	@echo "Creating a $(1) on GitHub..."
	@set -e; \
	read -p "Enter $(1) tag (e.g., $(shell date +%Y-%m-%d)): " TAG_NAME; \
	read -p "Enter $(1) title: " RELEASE_TITLE; \
	read -p "Enter $(1) notes: " RELEASE_NOTES; \
	if git rev-parse "$$TAG_NAME" >/dev/null 2>&1; then \
		echo "Error: Tag '$$TAG_NAME' already exists. Please choose a different tag."; \
		exit 1; \
	fi; \
	git tag -a $$TAG_NAME -m "$$RELEASE_TITLE"; \
	git push origin $$TAG_NAME; \
	gh release create $$TAG_NAME --title "$$RELEASE_TITLE" --notes "$$RELEASE_NOTES" $(if $(filter $(1),pre-release),--prerelease) --repo $(REPO_OWNER)/$(REPO_NAME); \
	while IFS= read -r tarball; do \
		[ -n "$$tarball" ] || continue; \
		gh release upload "$$TAG_NAME" "$$tarball" --repo $(REPO_OWNER)/$(REPO_NAME); \
	done < "$(RELEASE_ARTIFACT_MANIFEST)"; \
	$(MAKE) -f "$(SELF_MAKEFILE)" cleanup-release-artifacts; \
	echo "$(capitalize $(1)) $$TAG_NAME created successfully."
endef

define create_tag
	@echo "Creating a release on GitHub..."
	@set -e; \
	read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	git tag -a $$TAG -m "$$RELEASE_TITLE"; \
	git push origin $$TAG; \
	while IFS= read -r tarball; do \
		[ -n "$$tarball" ] || continue; \
		gh release upload "$$TAG" "$$tarball" --repo $(REPO_OWNER)/$(REPO_NAME); \
	done < "$(RELEASE_ARTIFACT_MANIFEST)"; \
	$(MAKE) -f "$(SELF_MAKEFILE)" cleanup-release-artifacts; \
	echo "Release $$TAG created successfully."
endef

capitalize = $(subst $(1),$(shell echo $(1) | tr '[:lower:]' '[:upper:]'),$(1))

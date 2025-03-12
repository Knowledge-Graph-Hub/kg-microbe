# Define variables
RUNNER_VERSION := 2.317.0
RUNNER_URL := https://github.com/actions/runner/releases/download/v$(RUNNER_VERSION)/actions-runner-linux-x64-$(RUNNER_VERSION).tar.gz
RUNNER_DIR := actions-runner
REPO_OWNER := Knowledge-Graph-Hub
REPO_NAME := kg-microbe
REPO_URL := https://github.com/$(REPO_OWNER)/$(REPO_NAME)
TOKEN := $(GH_TOKEN)
MERGED_TARBALL := data_merged.tar.gz
PART_SIZE := 2000M  # Size of each part (less than 2GB)
# Detect OS and set STAT_CMD accordingly
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Linux)
	STAT_CMD = stat -c %s
else ifeq ($(UNAME_S),Darwin)
	STAT_CMD = stat -f %z
endif

.PHONY: release pre-release tag generate-tarballs check-and-split

git_remote:
	@if [ -z "$(GH_TOKEN)" ]; then \
	  echo "Error: GH_TOKEN is not set. Aborting."; \
	  exit 1; \
	fi
	git remote set-url origin "https://$(GH_TOKEN)@github.com/Knowledge-Graph-Hub/kg-microbe.git"

release: git_remote generate-tarballs
	@$(call create_release,release)

pre-release: git_remote generate-tarballs
	$(call create_release,pre-release)

tag: generate-tarballs
	@$(call create_tag)

generate-tarballs:
	@echo "Generating tarballs of the specified directories..."
	@for dir in data/transformed/*; do \
		if [ -d "$$dir" ] && [ "$$(basename $$dir)" != "uniprot_functional_microbes" ]; then \
			if [ $$(find $$dir -type f | wc -l) -gt 0 ]; then \
				tarball_name=$$(basename $$dir).tar.gz; \
				tar -czvf $$tarball_name -C $$dir .; \
				echo "Tarball generated successfully as $$tarball_name."; \
				$(MAKE) check-and-split TARFILE=$$tarball_name DIR=$$dir; \
			else \
				echo "Directory $$dir is empty. Skipping tarball generation."; \
			fi \
		fi \
	done

	@if [ -d "data/merged/kg-microbe-core" ]; then \
		echo "Tarballing data/merged/kg-microbe-core..."; \
		tar -czvf kg-microbe-core.tar.gz -C data/merged/kg-microbe-core .; \
		echo "Tarball generated successfully as kg-microbe-core.tar.gz."; \
		$(MAKE) check-and-split TARFILE=kg-microbe-core.tar.gz DIR=data/merged/kg-microbe-core; \
	else \
		echo "Directory data/merged/kg-microbe-core does not exist. Skipping."; \
	fi

	@if [ -d "data/merged/kg-microbe-biomedical" ]; then \
		echo "Tarballing data/merged/kg-microbe-biomedical..."; \
		tar -czvf kg-microbe-biomedical.tar.gz -C data/merged/kg-microbe-biomedical .; \
		echo "Tarball generated successfully as kg-microbe-biomedical.tar.gz."; \
		$(MAKE) check-and-split TARFILE=kg-microbe-biomedical.tar.gz DIR=data/merged/kg-microbe-biomedical; \
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
				echo "Tarball generated successfully as $$tarball_name."; \
			else \
				echo "$$file is not a regular file. Skipping."; \
			fi \
		done; \
		rm -f $(TARFILE); \
		echo "$(TARFILE) deleted after splitting."; \
	else \
		echo "$(TARFILE) is less than 2GB. No need to split."; \
	fi

define create_release
	@echo "Creating a $(1) on GitHub..."
	@read -p "Enter $(1) tag (e.g., $(shell date +%Y-%m-%d)): " TAG_NAME; \
	read -p "Enter $(1) title: " RELEASE_TITLE; \
	read -p "Enter $(1) notes: " RELEASE_NOTES; \
	if git rev-parse "$$TAG_NAME" >/dev/null 2>&1; then \
		echo "Error: Tag '$$TAG_NAME' already exists. Please choose a different tag."; \
		exit 1; \
	fi; \
	git tag -a $$TAG_NAME -m "$$RELEASE_TITLE"; \
	git push origin $$TAG_NAME; \
	gh release create $$TAG_NAME --title "$$RELEASE_TITLE" --notes "$$RELEASE_NOTES" $(if $(filter $(1),pre-release),--prerelease) --repo $(REPO_OWNER)/$(REPO_NAME); \
	for tarball in *.tar.gz; do \
		gh release upload $$TAG_NAME $$tarball --repo $(REPO_OWNER)/$(REPO_NAME); \
	done; \
	rm -f *.tar.gz; \
	echo "$(capitalize $(1)) $$TAG_NAME created successfully."
endef

define create_tag
	@echo "Creating a release on GitHub..."
	@read -p "Enter release tag (e.g., $(shell date +%Y-%m-%d)): " TAG; \
	read -p "Enter release title: " RELEASE_TITLE; \
	read -p "Enter release notes: " RELEASE_NOTES; \
	git tag -a $$TAG -m "$$RELEASE_TITLE"; \
	git push origin $$TAG; \
	for tarball in *.tar.gz; do \
		gh release upload $$TAG $$tarball --repo $(REPO_OWNER)/$(REPO_NAME); \
	done; \
	rm -f *.tar.gz; \
	echo "Release $$TAG created successfully."
endef

capitalize = $(subst $(1),$(shell echo $(1) | tr '[:lower:]' '[:upper:]'),$(1))

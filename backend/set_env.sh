#!/bin/bash

# This script sets up environment variables for API keys

# Copy template environment file
echo "Setting up environment variables..."
cp temp.env .env

# Function to update API key in .env file
update_api_key() {
    local key_name=$1
    local key_value=$2
    sed -i "" "s|$key_name=.*|$key_name=$key_value|g" .env
}

# Function to check if key needs update
#!/bin/bash

echo "Setting up environment variables..."

# Nếu chưa có .env thì mới copy
if [ ! -f .env ]; then
    cp temp.env .env
fi

update_api_key() {
    local key_name=$1
    local key_value=$2
    sed -i "" "s|$key_name=.*|$key_name=$key_value|g" .env
}

needs_update() {
    local value=$1
    [[ -z "$value" || "$value" == "api_key_here" || "$value" == "gapi_key_here" ]]
}

for key in ANTHROPIC_API_KEY GROQ_API_KEY OPENAI_API_KEY; do
    current_value="${!key}"

    if needs_update "$current_value"; then
        echo "$key is not set → skipping (AI disabled)"
        continue
    else
        update_api_key "$key" "$current_value"
    fi
done

echo "Final API Keys:"
grep -E "^(ANTHROPIC|GROQ|OPENAI)_API_KEY=" .env || echo "No API keys set"

echo "Environment setup complete!"
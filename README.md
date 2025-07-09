# GeekStack Automations

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/yourusername/geekstack-automations/main.yml) ![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)

A web monitoring and data collection system that automatically tracks changes on Gundam, Duel Master, and One Piece websites, scrapes updated content, stores images in Google Cloud Storage, and saves data to MongoDB.

## Features

- **Automated Website Monitoring**: Regularly checks official Gundam, Duel Master, and One Piece websites for updates
- **Change Detection**: Identifies new content or modifications to existing content
- **Data Scraping**: Extracts relevant information when changes are detected
- **Image Handling**: Downloads images and uploads them to Google Cloud Storage (GCS)
- **Data Storage**: Stores structured data in MongoDB for easy access and analysis
- **Scheduled Execution**: Runs on a configurable schedule to ensure timely updates

## How It Works

1. **Monitoring**: The system periodically checks target websites for changes
2. **Detection**: When changes are found, it identifies new or modified content
3. **Scraping**: Relevant data is extracted from the updated pages
4. **Image Processing**:
   - Images are downloaded
   - Uploaded to Google Cloud Storage
   - URLs are stored for reference
5. **Data Storage**: All scraped data is structured and saved to MongoDB

## Technologies Used

- Python 3.8+
- BeautifulSoup/Scrapy for web scraping
- Requests for HTTP operations
- Google Cloud Storage Python client
- PyMongo for MongoDB interactions
- APScheduler for scheduling (or alternative)
- Docker (optional for containerization)

## Setup

### Prerequisites

- Python 3.8 or higher
- Google Cloud account with Storage access
- MongoDB instance (local or cloud)
- Required Python packages (see requirements.txt)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/geekstack-automations.git
   cd geekstack-automations
   ```

2. Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   Create a `.env` file with the following variables:
   ```
   GCS_BUCKET_NAME=your-bucket-name
   GCS_CREDENTIALS_PATH=path/to/your/service-account.json
   MONGO_URI=mongodb://username:password@host:port/database
   MONGO_DB_NAME=your_database_name
   ```

5. Run the application:
   ```bash
   python main.py
   ```

## Configuration

Modify `config.yaml` to customize:
- Target websites and their specific selectors
- Monitoring frequency
- Data extraction patterns
- Storage locations and naming conventions

## Deployment

For production deployment, consider:
- Running as a cron job or scheduled task
- Containerizing with Docker
- Deploying on cloud functions or a small VM

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This project is for educational purposes only. Please respect websites' terms of service and robots.txt files when scraping.

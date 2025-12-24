import requests
import json
from typing import Dict, Any, Optional, Union
from urllib.parse import urljoin

class ApiService:
    """
    API service class that provides axios-like functionality using requests
    """
    
    def __init__(self, base_url: str = "", default_headers: Optional[Dict[str, str]] = None, timeout: int = 30):
        """
        Initialize the API service
        
        Args:
            base_url: Base URL for all requests
            default_headers: Default headers to include in all requests
            timeout: Default timeout for requests in seconds
        """
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set default headers
        self.default_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'API-Client/1.0'
        }
        
        if default_headers:
            self.default_headers.update(default_headers)
        
        self.session.headers.update(self.default_headers)
    
    def _build_url(self, endpoint: str) -> str:
        """Build complete URL from base_url and endpoint"""
        if endpoint.startswith('http'):
            return endpoint
        return urljoin(self.base_url, endpoint)
    
    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        Handle response and return standardized format
        
        Returns:
            Dict with status, data, headers, and success flag
        """
        try:
            # Try to parse JSON response
            if response.headers.get('content-type', '').startswith('application/json'):
                data = response.json()
            else:
                data = response.text
        except json.JSONDecodeError:
            data = response.text
        
        return {
            'status': response.status_code,
            'data': data,
            'headers': dict(response.headers),
            'success': 200 <= response.status_code < 300,
            'url': response.url
        }
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, 
            headers: Optional[Dict[str, str]] = None, **kwargs) -> Dict[str, Any]:
        """
        Perform GET request (axios.get equivalent)
        
        Args:
            endpoint: API endpoint or full URL
            params: Query parameters
            headers: Additional headers for this request
            **kwargs: Additional arguments for requests.get
        
        Returns:
            Response dict with status, data, headers, success
        """
        url = self._build_url(endpoint)
        
        # Merge headers
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            response = self.session.get(
                url, 
                params=params, 
                headers=request_headers,
                timeout=kwargs.get('timeout', self.timeout),
                **{k: v for k, v in kwargs.items() if k != 'timeout'}
            )
            return self._handle_response(response)
        except requests.RequestException as e:
            return {
                'status': 0,
                'data': str(e),
                'headers': {},
                'success': False,
                'url': url,
                'error': str(e)
            }
    
    def post(self, endpoint: str, data: Optional[Union[Dict[str, Any], str]] = None,
             json_data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
             **kwargs) -> Dict[str, Any]:
        """
        Perform POST request (axios.post equivalent)
        
        Args:
            endpoint: API endpoint or full URL
            data: Form data or string data
            json_data: JSON data (will be serialized automatically)
            headers: Additional headers for this request
            **kwargs: Additional arguments for requests.post
        
        Returns:
            Response dict with status, data, headers, success
        """
        url = self._build_url(endpoint)
        
        # Merge headers
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            # Handle different data types
            if json_data is not None:
                response = self.session.post(
                    url,
                    json=json_data,
                    headers=request_headers,
                    timeout=kwargs.get('timeout', self.timeout),
                    **{k: v for k, v in kwargs.items() if k != 'timeout'}
                )
            else:
                response = self.session.post(
                    url,
                    data=data,
                    headers=request_headers,
                    timeout=kwargs.get('timeout', self.timeout),
                    **{k: v for k, v in kwargs.items() if k != 'timeout'}
                )
            
            return self._handle_response(response)
        except requests.RequestException as e:
            return {
                'status': 0,
                'data': str(e),
                'headers': {},
                'success': False,
                'url': url,
                'error': str(e)
            }
    
    def put(self, endpoint: str, data: Optional[Union[Dict[str, Any], str]] = None,
            json_data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
            **kwargs) -> Dict[str, Any]:
        """Perform PUT request"""
        url = self._build_url(endpoint)
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            if json_data is not None:
                response = self.session.put(
                    url, json=json_data, headers=request_headers,
                    timeout=kwargs.get('timeout', self.timeout), **kwargs
                )
            else:
                response = self.session.put(
                    url, data=data, headers=request_headers,
                    timeout=kwargs.get('timeout', self.timeout), **kwargs
                )
            return self._handle_response(response)
        except requests.RequestException as e:
            return {
                'status': 0, 'data': str(e), 'headers': {},
                'success': False, 'url': url, 'error': str(e)
            }
    
    def delete(self, endpoint: str, headers: Optional[Dict[str, str]] = None, **kwargs) -> Dict[str, Any]:
        """Perform DELETE request"""
        url = self._build_url(endpoint)
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            response = self.session.delete(
                url, headers=request_headers,
                timeout=kwargs.get('timeout', self.timeout), **kwargs
            )
            return self._handle_response(response)
        except requests.RequestException as e:
            return {
                'status': 0, 'data': str(e), 'headers': {},
                'success': False, 'url': url, 'error': str(e)
            }
    
    def set_auth(self, auth: Union[tuple, requests.auth.AuthBase]):
        """Set authentication for all requests"""
        self.session.auth = auth
    
    def set_header(self, key: str, value: str):
        """Set a default header for all requests"""
        self.default_headers[key] = value
        self.session.headers[key] = value
    
    def set_bearer_token(self, token: str):
        """Set Bearer token for authorization"""
        self.set_header('Authorization', f'Bearer {token}')
    
    def set_api_key(self, key: str, header_name: str = 'X-API-Key'):
        """Set API key header"""
        self.set_header(header_name, key)


# Example usage and utility functions
def create_api_client(base_url: str, headers: Optional[Dict[str, str]] = None) -> ApiService:
    """Factory function to create API client"""
    return ApiService(base_url=base_url, default_headers=headers)


# Example usage:
if __name__ == "__main__":
    # Create API client
    api = ApiService("https://jsonplaceholder.typicode.com")
    
    # GET request example
    response = api.get("/posts/1")
    if response['success']:
        print("GET Success:", response['data'])
    else:
        print("GET Error:", response['data'])
    
    # POST request example
    post_data = {
        "title": "Test Post",
        "body": "This is a test post",
        "userId": 1
    }
    response = api.post("/posts", json_data=post_data)
    if response['success']:
        print("POST Success:", response['data'])
    else:
        print("POST Error:", response['data'])
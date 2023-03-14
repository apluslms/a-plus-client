A+ API client library
=====================

Tool to help access A+ API in grading tools or in local scripts.


Installation
------------

.. code-block:: sh

  pip install 'git+https://github.com/apluslms/a-plus-client.git@v1.2.0#egg=a_plus_client'


Usage examples
--------------

**Downloading course points from the A+ API one student at a time**

.. code-block:: python

  import csv
  import sys
  from typing import Collection, Dict, Sequence

  from aplus_client.client import AplusTokenClient


  def write_csv(file_path, data: Sequence[Dict[str, str]], field_names: Collection[str]):
      with open(file_path, 'w', newline='') as f:
          writer = csv.DictWriter(f, fieldnames=field_names, extrasaction='ignore')
          writer.writeheader()
          for record in data:
              writer.writerow(record)


  course_instance_id = 1 # Change this to the correct CourseInstance.id
  output_file_path = "course_points.csv"

  token = "XXX" # copy the token from your A+ user profile page
  client = AplusTokenClient(token, version=2)
  client.set_base_url_from('https://plus.cs.aalto.fi/api/v2/')

  students = client.load_data(f'/courses/{course_instance_id}/students/?format=json', skip_cache=True)

  field_names = [
      'student number',
      'full name',
  ]
  data = []
  for student in students:
      user_id = student.get('id')
      try:
          points_json = client.load_data(f'/courses/{course_instance_id}/points/{user_id}/?format=json', skip_cache=True)
      except Exception as e:
          print(f"Error: HTTP API. UID {user_id}, student id {student.get('student_id', 'None')} | {e}", file=sys.stderr)
      else:
          points = {
              'student number': student.get('student_id', 'None'),
              'full name': student.get('full_name', 'None'),
          }
          for module in points_json['modules']:
              module_name = module['name']
              points[module_name] = module.get('points', 0)
              if module_name not in field_names:
                  field_names.append(module_name)

          data.append(points)

  write_csv(output_file_path, data, field_names)

